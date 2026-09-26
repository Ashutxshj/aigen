"""SQLite working store (leeds/leads.db). Every stage reads and writes here, so
each stage is independently re-runnable: a failed Gemini run never forces a
re-scrape.

Dedup is the DATABASE's job, not Python's:
  * UNIQUE(source_uid) + INSERT OR IGNORE — a post can never re-surface. The
    sibling master_registry reads every row into a set on each run, which is
    O(n), not concurrency-safe, and swallows errors. Not repeated here.
  * person_key   ("u/foo@reddit") — author cooldown, so one prolific poster
    cannot fill the sheet.
  * content_hash (normalised-text simhash) — catches the same person crossposting
    the identical question to five subs, which is extremely common.
  * watermarks(collector, scope, last_seen_id, last_run_at) is an EFFICIENCY
    device to stop paginating early. It is NOT dedup. You need both.
"""

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import config
from core import log
from core.models import Lead, Signal, Verdict, ensure_utc, utcnow

logger = log.get("store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    source_uid      TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    source_detail   TEXT DEFAULT '',
    username        TEXT DEFAULT '',
    person_key      TEXT DEFAULT '',
    permalink       TEXT DEFAULT '',
    post_title      TEXT DEFAULT '',
    body            TEXT DEFAULT '',
    posted_at       TEXT NOT NULL,          -- ISO-8601, always +00:00
    collected_at    TEXT NOT NULL,
    signal_type     TEXT DEFAULT 'stated_problem',
    phone           TEXT DEFAULT '',
    email           TEXT DEFAULT '',
    website         TEXT DEFAULT '',
    region          TEXT DEFAULT '',
    country         TEXT DEFAULT '',
    geo_method      TEXT DEFAULT '',
    business_type   TEXT DEFAULT '',
    contact_channel TEXT DEFAULT '',
    other_profiles  TEXT DEFAULT '',
    raw             TEXT DEFAULT '{}',
    content_hash    TEXT DEFAULT '',
    -- scoring
    score_rule      INTEGER,
    score_llm       INTEGER,
    score           INTEGER,
    intent_tier     TEXT DEFAULT '',
    intent_signals  TEXT DEFAULT '[]',
    verdict         TEXT DEFAULT '{}',
    scored_at       TEXT,
    enriched_at     TEXT,
    -- draft
    opener          TEXT DEFAULT '',
    opener_channel  TEXT DEFAULT '',
    draft_status    TEXT DEFAULT '',
    drafted_at      TEXT,
    -- HUMAN-OWNED. Written by the human in Excel, merged back on export,
    -- and NEVER overwritten by any stage of this pipeline.
    status          TEXT DEFAULT '',
    contacted       TEXT DEFAULT '',
    do_not_contact  TEXT DEFAULT '',
    notes           TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_signals_person  ON signals(person_key);
CREATE INDEX IF NOT EXISTS ix_signals_hash    ON signals(content_hash);
CREATE INDEX IF NOT EXISTS ix_signals_posted  ON signals(posted_at);

CREATE TABLE IF NOT EXISTS buckets (
    key           TEXT PRIMARY KEY,
    tokens        REAL NOT NULL,
    updated_at    REAL NOT NULL,
    day           TEXT NOT NULL,
    day_used      INTEGER NOT NULL DEFAULT 0,
    blocked_until REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watermarks (
    collector    TEXT NOT NULL,
    scope        TEXT NOT NULL,
    last_seen_id TEXT DEFAULT '',
    last_run_at  TEXT DEFAULT '',
    PRIMARY KEY (collector, scope)
);

CREATE TABLE IF NOT EXISTS http_cache (
    url           TEXT PRIMARY KEY,
    etag          TEXT DEFAULT '',
    last_modified TEXT DEFAULT '',
    body          TEXT DEFAULT '',
    fetched_at    TEXT DEFAULT ''
);

-- Gemini responses keyed by content hash: re-running `score` on an unchanged
-- corpus must cost ZERO requests.
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    collector       TEXT NOT NULL,
    items_fetched   INTEGER DEFAULT 0,
    items_kept      INTEGER DEFAULT 0,
    gemini_requests INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    detail          TEXT DEFAULT ''
);
"""

_WORD_RE = re.compile(r"[a-z0-9']+")


def content_hash(text: str) -> str:
    """Order-insensitive hash of the significant words. Two crossposts of the
    same question — reformatted, retitled — collapse to the same hash."""
    words = sorted(set(_WORD_RE.findall(text.lower())))
    words = [w for w in words if len(w) > 2][:120]
    return hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str = ""):
        self.path = path or config.DB_PATH
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- signals -------------------------------------------------------------

    def add_signals(self, signals: Iterable[Signal]) -> int:
        """INSERT OR IGNORE. Returns the number of genuinely NEW rows."""
        new = 0
        for sig in signals:
            chash = content_hash(sig.text())
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO signals (
                     source_uid, platform, source_detail, username, person_key,
                     permalink, post_title, body, posted_at, collected_at,
                     signal_type, phone, email, website, region, country,
                     geo_method, business_type, contact_channel, raw, content_hash
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sig.source_uid, sig.platform, sig.source_detail, sig.username,
                 sig.person_key, sig.permalink, sig.post_title, sig.body,
                 sig.posted_at.isoformat(), sig.collected_at.isoformat(),
                 sig.signal_type, sig.phone, sig.email, sig.website, sig.region,
                 sig.country, sig.geo_method, sig.business_type,
                 sig.contact_channel, json.dumps(sig.raw, default=str), chash))
            new += cur.rowcount
        self.conn.commit()
        return new

    @staticmethod
    def _signal(row: sqlite3.Row) -> Signal:
        return Signal(
            source_uid=row["source_uid"], platform=row["platform"],
            source_detail=row["source_detail"], username=row["username"],
            person_key=row["person_key"], permalink=row["permalink"],
            post_title=row["post_title"], body=row["body"],
            posted_at=ensure_utc(row["posted_at"]),
            collected_at=ensure_utc(row["collected_at"]),
            signal_type=row["signal_type"], phone=row["phone"],
            email=row["email"], website=row["website"], region=row["region"],
            country=row["country"], geo_method=row["geo_method"],
            business_type=row["business_type"],
            contact_channel=row["contact_channel"],
            raw=json.loads(row["raw"] or "{}"))

    def _lead(self, row: sqlite3.Row) -> Lead:
        return Lead(
            signal=self._signal(row),
            score_rule=row["score_rule"] or 0,
            score_llm=row["score_llm"] or 0,
            score=row["score"] or 0,
            intent_tier=row["intent_tier"] or "",
            intent_signals=json.loads(row["intent_signals"] or "[]"),
            verdict=Verdict(**json.loads(row["verdict"] or "{}")),
            opener=row["opener"] or "",
            opener_channel=row["opener_channel"] or "",
            draft_status=row["draft_status"] or "",
            other_profiles=row["other_profiles"] or "")

    def fresh_signals(self, since: datetime, platform: str = "",
                      unscored_only: bool = False) -> list[Signal]:
        sql = "SELECT * FROM signals WHERE posted_at >= ?"
        args: list[Any] = [ensure_utc(since).isoformat()]
        if platform:
            sql += " AND platform = ?"
            args.append(platform)
        if unscored_only:
            sql += " AND scored_at IS NULL"
        sql += " ORDER BY posted_at DESC"
        return [self._signal(r) for r in self.conn.execute(sql, args)]

    def leads(self, since: datetime, min_score: int = 0, platform: str = "",
              drafted_only: bool = False) -> list[Lead]:
        sql = ("SELECT * FROM signals WHERE posted_at >= ? AND scored_at IS NOT "
               "NULL AND score >= ?")
        args: list[Any] = [ensure_utc(since).isoformat(), min_score]
        if platform:
            sql += " AND platform = ?"
            args.append(platform)
        if drafted_only:
            sql += " AND opener != ''"
        # Freshest + highest intent first.
        sql += " ORDER BY score DESC, posted_at DESC"
        return [self._lead(r) for r in self.conn.execute(sql, args)]

    # --- scoring / enrich / draft writeback ----------------------------------

    def save_score(self, lead: Lead) -> None:
        self.conn.execute(
            "UPDATE signals SET score_rule=?, score_llm=?, score=?, "
            "intent_tier=?, intent_signals=?, verdict=?, scored_at=? "
            "WHERE source_uid=?",
            (lead.score_rule, lead.score_llm, lead.score, lead.intent_tier,
             json.dumps(lead.intent_signals),
             lead.verdict.model_dump_json(), utcnow().isoformat(),
             lead.signal.source_uid))
        self.conn.commit()

    def save_enrichment(self, source_uid: str, **fields: str) -> None:
        allowed = {"phone", "email", "website", "region", "country",
                   "geo_method", "business_type", "contact_channel",
                   "other_profiles"}
        sets = {k: v for k, v in fields.items() if k in allowed and v}
        if not sets:
            self.conn.execute(
                "UPDATE signals SET enriched_at=? WHERE source_uid=?",
                (utcnow().isoformat(), source_uid))
            self.conn.commit()
            return
        clause = ", ".join(f"{k}=?" for k in sets)
        self.conn.execute(
            f"UPDATE signals SET {clause}, enriched_at=? WHERE source_uid=?",
            (*sets.values(), utcnow().isoformat(), source_uid))
        self.conn.commit()

    def save_draft(self, source_uid: str, opener: str, channel: str,
                   status: str) -> None:
        self.conn.execute(
            "UPDATE signals SET opener=?, opener_channel=?, draft_status=?, "
            "drafted_at=? WHERE source_uid=?",
            (opener, channel, status, utcnow().isoformat(), source_uid))
        self.conn.commit()

    # --- human-owned columns -------------------------------------------------

    def merge_human_edits(self, rows: dict[str, dict[str, str]]) -> int:
        """Pull the human's Excel edits BACK into SQLite, keyed by source_uid.

        This is the fix for the real bug in the original spec: rewriting the
        sheet from the DB every run silently wiped whatever the human typed into
        Status / Notes. Export calls this BEFORE it rewrites anything.
        """
        touched = 0
        for uid, vals in rows.items():
            cur = self.conn.execute(
                "UPDATE signals SET status=?, contacted=?, do_not_contact=?, "
                "notes=? WHERE source_uid=?",
                (vals.get("status", ""), vals.get("contacted", ""),
                 vals.get("do_not_contact", ""), vals.get("notes", ""), uid))
            touched += cur.rowcount
        self.conn.commit()
        return touched

    def uid_for_permalink(self, permalink: str) -> str:
        """The sheet identifies rows by Permalink (Lead ID was removed as
        human-hostile); the DB still keys on source_uid. This is the bridge."""
        row = self.conn.execute(
            "SELECT source_uid FROM signals WHERE permalink=?",
            (permalink,)).fetchone()
        return row[0] if row else ""

    def human_fields(self, source_uid: str) -> dict[str, str]:
        row = self.conn.execute(
            "SELECT status, contacted, do_not_contact, notes FROM signals "
            "WHERE source_uid=?", (source_uid,)).fetchone()
        if row is None:
            return {"status": "", "contacted": "", "do_not_contact": "",
                    "notes": ""}
        return dict(row)

    # --- dedup helpers -------------------------------------------------------

    def duplicate_hashes(self, since: datetime) -> set[str]:
        """content_hashes that appear more than once (crossposts). The export
        keeps the highest-scoring copy; score.py flags the rest."""
        rows = self.conn.execute(
            "SELECT content_hash FROM signals WHERE posted_at >= ? "
            "GROUP BY content_hash HAVING COUNT(*) > 1",
            (ensure_utc(since).isoformat(),))
        return {r[0] for r in rows if r[0]}

    def author_post_count(self, person_key: str, since: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM signals WHERE person_key=? AND posted_at>=?",
            (person_key, ensure_utc(since).isoformat())).fetchone()
        return int(row[0])

    # --- watermarks ----------------------------------------------------------

    def watermark(self, collector: str, scope: str) -> str:
        row = self.conn.execute(
            "SELECT last_seen_id FROM watermarks WHERE collector=? AND scope=?",
            (collector, scope)).fetchone()
        return row[0] if row else ""

    def set_watermark(self, collector: str, scope: str, last_seen_id: str) -> None:
        self.conn.execute(
            "INSERT INTO watermarks (collector, scope, last_seen_id, last_run_at)"
            " VALUES (?,?,?,?) ON CONFLICT(collector, scope) DO UPDATE SET "
            "last_seen_id=excluded.last_seen_id, last_run_at=excluded.last_run_at",
            (collector, scope, last_seen_id, utcnow().isoformat()))
        self.conn.commit()

    # --- http conditional cache ---------------------------------------------

    def cached_http(self, url: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT etag, last_modified, body FROM http_cache WHERE url=?",
            (url,)).fetchone()

    def save_http(self, url: str, etag: str, last_modified: str,
                  body: str) -> None:
        self.conn.execute(
            "INSERT INTO http_cache (url, etag, last_modified, body, fetched_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
            "etag=excluded.etag, last_modified=excluded.last_modified, "
            "body=excluded.body, fetched_at=excluded.fetched_at",
            (url, etag, last_modified, body, utcnow().isoformat()))
        self.conn.commit()

    # --- llm cache -----------------------------------------------------------

    def llm_cached(self, key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT response FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("corrupt llm_cache row for %s — ignoring", key)
            return None

    def llm_store(self, key: str, response: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response, created_at) "
            "VALUES (?,?,?)",
            (key, json.dumps(response), utcnow().isoformat()))
        self.conn.commit()

    # --- runs ----------------------------------------------------------------

    def record_run(self, run_id: str, started_at: datetime, collector: str,
                   fetched: int, kept: int, gemini_requests: int, errors: int,
                   detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO runs (run_id, started_at, collector, items_fetched, "
            "items_kept, gemini_requests, errors, detail) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, ensure_utc(started_at).isoformat(), collector, fetched,
             kept, gemini_requests, errors, detail))
        self.conn.commit()

    def recent_runs(self, limit: int = 200) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (limit,)))
