"""Google search — the widest net in the repo.

Every other collector is limited to ONE platform's own API. This one searches the
whole indexed web, which means it reaches the places that have no API at all:
Quora, niche trade forums, Facebook pages, local directories, WordPress/Shopify
community threads, and Reddit itself. It is also a SECOND, independent route to
Reddit posts — so if Arctic Shift is down, intent still comes in.

## Which API, and why not the others

**Google Programmable Search Engine (CSE) JSON API.** Free tier: **100 queries a
day**, no card. Two credentials, both free, both take two minutes:

  1. GOOGLE_CSE_KEY  — an API key with "Custom Search API" enabled:
     https://console.cloud.google.com/apis/library/customsearch.googleapis.com
     (This is NOT your GEMINI_API_KEY. Different product, different key.)
  2. GOOGLE_CSE_CX   — a search engine id from
     https://programmablesearchengine.google.com/  →  create  →  and you MUST
     turn ON "Search the entire web". A CSE defaults to searching only the sites
     you list, which would silently return nothing and look like "no leads".

**Brave Search API** is supported as a fallback: 2,000 queries/month free, also no
card. Set BRAVE_API_KEY.

**Not scraping google.com/search.** It is against their ToS, it serves CAPTCHAs to
datacenter IPs within a handful of queries, and it would make the tool's results
silently degrade rather than fail. A free 100/day that WORKS beats an unlimited
scraper that gets blocked on Tuesday.

## The freshness problem, and the flag that solves it

A search engine's index is not a firehose — by default you get the best results,
not the newest, and "best" for these queries is a five-year-old thread that ranks
well and where the poster hired someone in 2021. That is useless.

`dateRestrict=d2` fixes it: Google returns only pages it indexed in the last two
days. That is the whole reason this collector can honour a 48h window at all.
Brave's equivalent is `freshness=pd` (past day) / `pw` (past week).

## Budget

100 queries/day is the binding constraint, and each query is one request. With
~12 query templates and one page each, a run costs ~12 of your 100 — so you can
run this hourly and still not run out. Do NOT paginate greedily; the second page
of results for these queries is almost always noise.
"""

import re
from datetime import datetime, timedelta

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc, utcnow

logger = log.get("websearch")

CSE_URL = "https://www.googleapis.com/customsearch/v1"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"

_SUB_RE = re.compile(r"reddit\.com/r/([A-Za-z0-9_]+)", re.I)


class WebSearchCollector(Collector):
    name = "websearch"
    bucket = "websearch"

    def available(self) -> tuple[bool, str]:
        if self.mock:
            return True, ""
        if config.GOOGLE_CSE_KEY and config.GOOGLE_CSE_CX:
            return True, ""
        if config.BRAVE_API_KEY:
            return True, ""
        return False, (
            "no search key. Google CSE (free, 100/day): set GOOGLE_CSE_KEY + "
            "GOOGLE_CSE_CX — and switch ON 'Search the entire web' when you "
            "create the engine, or it returns nothing. Or set BRAVE_API_KEY "
            "(free, 2000/month).")

    # --- providers -----------------------------------------------------------

    def _google(self, query: str, days: int) -> list[dict]:
        payload = self.api.get_json(
            CSE_URL, self.bucket,
            params={
                "key": config.GOOGLE_CSE_KEY,
                "cx": config.GOOGLE_CSE_CX,
                "q": query,
                "num": 10,
                # Without this you get the best-ranking thread, not a recent one —
                # and the best-ranking "I need a website" thread is from 2019 and
                # the poster hired somebody five years ago.
                "dateRestrict": f"d{max(1, days)}",
                "safe": "off",
            })
        if payload is None:
            return []
        if "error" in payload:
            msg = payload["error"].get("message", "")
            logger.error("google cse: %s", msg[:200])
            if "quota" in msg.lower() or "limit" in msg.lower():
                logger.error("that is the 100/day free quota. It resets at "
                             "midnight Pacific.")
            return []
        return payload.get("items") or []

    def _brave(self, query: str, days: int) -> list[dict]:
        resp = self.api.get(
            BRAVE_URL, self.bucket,
            params={"q": query, "count": 10,
                    "freshness": "pd" if days <= 1 else "pw"},
            headers={"X-Subscription-Token": config.BRAVE_API_KEY,
                     "Accept": "application/json"})
        if resp is None or resp.status_code >= 400:
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        out = []
        for hit in (payload.get("web") or {}).get("results") or []:
            out.append({"link": hit.get("url"),
                        "title": hit.get("title"),
                        "snippet": hit.get("description")})
        return out

    # --- parsing -------------------------------------------------------------

    @staticmethod
    def _signal(hit: dict, query: str, now: datetime) -> Signal | None:
        link = (hit.get("link") or "").strip()
        title = (hit.get("title") or "").strip()
        snippet = (hit.get("snippet") or "").strip()
        if not link or not title:
            return None

        host = link.split("//", 1)[-1].split("/", 1)[0].lower().replace("www.", "")

        # If it IS a reddit thread, key it so it dedups against whatever the
        # Reddit collector already found. Two routes to the same post must not
        # produce two rows.
        sub = ""
        match = _SUB_RE.search(link)
        if match:
            sub = match.group(1)
            ids = re.search(r"/comments/([a-z0-9]+)", link, re.I)
            uid = f"reddit:t3_{ids.group(1)}" if ids else f"web:{link}"
        else:
            uid = f"web:{link}"

        return Signal(
            source_uid=uid,
            platform="reddit" if sub else "websearch",
            source_detail=sub or host,
            permalink=link,
            post_title=title,
            # A search result gives you a SNIPPET, not the post. That is enough to
            # score the intent, and the human opens the permalink to read the rest.
            # We do not fetch the page: that would be a second request per hit, a
            # robots.txt question per host, and 10x the runtime for text we are
            # about to show a human anyway.
            body=snippet,
            # Google will not tell us when the page was POSTED, only that it was
            # INDEXED within dateRestrict. Stamping "now" would be a lie that the
            # Age column then repeats. We stamp the edge of the window we asked
            # for, so the age is a floor, not a fabrication — and geo_method-style
            # honesty is preserved in `raw`.
            posted_at=now,
            signal_type="stated_problem",
            geo_method="",
            raw={"via": "websearch", "query": query,
                 "posted_at_is_approximate": True},
        )

    # --- fetch ---------------------------------------------------------------

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("websearch") or {}
            now = utcnow() - timedelta(hours=3)
            out = []
            for hit in raw.get("items", []):
                sig = self._signal(hit, "mock", now)
                if sig:
                    out.append(sig)
            return out

        now = utcnow()
        days = max(1, int((now - since).total_seconds() // 86400) or 1)
        use_google = bool(config.GOOGLE_CSE_KEY and config.GOOGLE_CSE_CX)

        out: list[Signal] = []
        for query in config.SEARCH_QUERIES:
            hits = (self._google(query, days) if use_google
                    else self._brave(query, days))
            logger.debug("%r -> %d hits", query, len(hits))
            for hit in hits:
                # A search result's timestamp is unknowable, so we cannot honour
                # the window precisely. dateRestrict already did that server-side;
                # stamp it just inside the window so base.run() keeps it.
                sig = self._signal(hit, query, since + timedelta(minutes=1))
                if sig:
                    out.append(sig)

        if not out:
            logger.warning(
                "web search returned nothing. If you just created the Custom "
                "Search Engine, check that 'Search the entire web' is ON — "
                "otherwise it only searches sites you explicitly listed, and "
                "returns zero for every query while looking perfectly healthy.")

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())
