"""Per-platform token bucket, PERSISTED in SQLite.

Why persisted: a bucket that lives in the process resets every run. Run the tool
twice in five minutes and you have silently doubled your request rate — which is
exactly how an API key gets suspended. State lives in the `buckets` table so the
budget holds across runs, across processes, and across a crash.

Two limit shapes, because real APIs use both:
  * a RATE   (tokens refilled per second)  — Reddit, Bluesky, Overpass...
  * a DAILY QUOTA (n calls per UTC day)    — Stack Exchange (300/day anonymous),
                                             WhoisDS (the feed only moves daily)
Stack Exchange also returns a mandatory `backoff` field in the response BODY;
`penalise()` parks the bucket for that long. Ignoring it gets you blocked.

The bucket KEY is declared by the collector, not derived from the host: Reddit's
limit is per OAuth client id, and Mastodon's is per instance, so mastodon.social
and mstdn.social get separate buckets ("mastodon:mastodon.social").
"""

import sqlite3
import time
from datetime import datetime, timezone

import config
from core import log

logger = log.get("ratelimit")

# Nothing in this repo is worth blocking a run for longer than this. A bucket
# whose refill rate is a per-DAY rate (newdomains: 1 token / 86400s) asked
# acquire() to sleep for 24 HOURS on the second call — the run just hung. If the
# wait is that absurd the honest answer is "skip this call", exactly as we do
# when a daily quota is exhausted.
MAX_SLEEP_SECONDS = 300.0


class RateLimiter:
    def __init__(self, conn: sqlite3.Connection, disabled: bool = False):
        self._conn = conn
        # --mock / --dry-run make zero outbound requests, so there is nothing to
        # limit; sleeping would just make the test suite slow.
        self._disabled = disabled

    # --- spec lookup ---------------------------------------------------------

    @staticmethod
    def _spec(key: str) -> tuple[float, float, int | None]:
        """Bucket keys may be namespaced ("mastodon:mastodon.social"); the spec
        is looked up on the family ("mastodon")."""
        family = key.split(":", 1)[0]
        spec = config.RATE_LIMITS.get(family)
        if spec is None:
            logger.warning("no rate limit configured for %r — defaulting to "
                           "1 req/2s", key)
            return (1.0, 0.5, None)
        capacity, rate, quota = spec
        if family == "stackexchange" and config.STACKEXCHANGE_KEY:
            quota = config.STACKEXCHANGE_QUOTA_WITH_KEY
        return capacity, rate, quota

    # --- persistence ---------------------------------------------------------

    def _row(self, key: str) -> tuple[float, float, str, int, float]:
        capacity, _, _ = self._spec(key)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = self._conn.execute(
            "SELECT tokens, updated_at, day, day_used, blocked_until "
            "FROM buckets WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO buckets (key, tokens, updated_at, day, day_used, "
                "blocked_until) VALUES (?, ?, ?, ?, 0, 0)",
                (key, capacity, time.time(), today))
            self._conn.commit()
            return capacity, time.time(), today, 0, 0.0
        return row[0], row[1], row[2], row[3], row[4]

    def _save(self, key: str, tokens: float, day: str, day_used: int,
              blocked_until: float) -> None:
        self._conn.execute(
            "UPDATE buckets SET tokens = ?, updated_at = ?, day = ?, "
            "day_used = ?, blocked_until = ? WHERE key = ?",
            (tokens, time.time(), day, day_used, blocked_until, key))
        self._conn.commit()

    # --- public --------------------------------------------------------------

    def acquire(self, key: str, cost: float = 1.0) -> bool:
        """Block until `cost` tokens are available, then spend them.

        Returns False (without sleeping) if the DAILY QUOTA for this key is
        exhausted — the caller must skip, not wait, because the quota will not
        refill for hours.
        """
        if self._disabled:
            return True

        capacity, rate, quota = self._spec(key)
        tokens, updated_at, day, day_used, blocked_until = self._row(key)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if day != today:                     # new UTC day: quota resets
            day, day_used = today, 0

        if quota is not None and day_used >= quota:
            logger.warning("%s: daily quota exhausted (%d/%d) — skipping",
                           key, day_used, quota)
            self._save(key, tokens, day, day_used, blocked_until)
            return False

        # A server-mandated penalty (Stack Exchange `backoff`, or a 429) parks
        # the whole bucket.
        wait = blocked_until - time.time()
        if wait > 0:
            logger.info("%s: honouring server backoff, sleeping %.1fs", key, wait)
            time.sleep(wait)

        # Refill, then spend — sleeping for whatever is still missing.
        now = time.time()
        tokens = min(capacity, tokens + (now - updated_at) * rate)
        if tokens < cost:
            need = (cost - tokens) / rate if rate > 0 else 60.0
            if need > MAX_SLEEP_SECONDS:
                # Do not hang the run for hours. Skip, and say so.
                logger.warning("%s: bucket would need %.0fs (%.1fh) to refill — "
                               "skipping this call rather than hanging the run",
                               key, need, need / 3600.0)
                self._save(key, tokens, day, day_used, blocked_until)
                return False
            logger.info("%s: bucket empty, sleeping %.1fs", key, need)
            time.sleep(need)
            tokens = min(capacity, tokens + need * rate)

        self._save(key, max(0.0, tokens - cost), day, day_used + 1, 0.0)
        return True

    def penalise(self, key: str, seconds: float) -> None:
        """Park the bucket for `seconds` (Retry-After, or SE's `backoff`)."""
        if self._disabled or seconds <= 0:
            return
        tokens, _, day, day_used, _ = self._row(key)
        until = time.time() + min(seconds, 3600.0)
        logger.warning("%s: server asked for %.0fs backoff", key, seconds)
        self._save(key, tokens, day, day_used, until)

    def observe_headers(self, key: str, headers) -> None:
        """Trust the server over our own table.

        Reddit returns X-Ratelimit-Remaining / X-Ratelimit-Reset on every OAuth
        call. If it says we have 3 calls left in this window, believe it and
        stretch them over the remaining seconds instead of guessing from config.
        """
        if self._disabled or not headers:
            return
        remaining = headers.get("X-Ratelimit-Remaining")
        reset = headers.get("X-Ratelimit-Reset")
        if remaining is None or reset is None:
            return
        try:
            remaining_f = float(remaining)
            reset_f = float(reset)
        except (TypeError, ValueError):
            return
        if remaining_f <= 1.0 and reset_f > 0:
            logger.warning("%s: %s calls left in window, parking %.0fs",
                           key, remaining, reset_f)
            self.penalise(key, reset_f)
