"""Reddit — the main source.

Auth: app-only OAuth (grant_type=client_credentials) against a free "script" app.
NOT the password grant: that ties every automated read to a human account, breaks
under 2FA, and is the fast route to the account trouble we are trying to avoid.
Read-only application auth needs no account at all.

The spine is /new AND /comments, not /search:
  * /new       chronological, authoritative, no index lag. This is what actually
               guarantees the 48h window.
  * /comments  roughly a third of "I need a website" intent is a COMMENT in a
               weekly megathread and never becomes its own post. A post-only
               collector silently misses all of it.
  * /search    a SUPPLEMENT only. Reddit's search index lags by minutes to hours
               and its recall is unreliable, so it can find things outside our
               sub list but must never be the thing we depend on for freshness.

No PRAW: it is a dependency to wrap forty lines, and it hides the X-Ratelimit-*
headers that we specifically want to read.
"""

import time
from datetime import datetime
from typing import Optional

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("reddit")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


class RedditCollector(Collector):
    name = "reddit"
    bucket = "reddit"          # Reddit limits per OAuth CLIENT ID, not per IP.

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._token: Optional[str] = None
        self._token_expires = 0.0

    def available(self) -> tuple[bool, str]:
        if self.mock:
            return True, ""
        if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
            return False, ("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set "
                           "(make a free 'script' app at reddit.com/prefs/apps)")
        return True, ""

    # --- auth -----------------------------------------------------------------

    def _auth(self) -> Optional[str]:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        resp = self.api.post(
            TOKEN_URL, self.bucket,
            data={"grant_type": "client_credentials"},
            auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
            headers={"User-Agent": config.REDDIT_USER_AGENT})
        if resp is None or resp.status_code != 200:
            logger.error("reddit auth failed (%s)",
                         resp.status_code if resp else "no response")
            return None
        payload = resp.json()
        self._token = payload.get("access_token")
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        logger.info("reddit: authenticated (app-only)")
        return self._token

    def _get(self, path: str, **params) -> Optional[dict]:
        token = self._auth()
        if not token:
            return None
        resp = self.api.get(
            f"{API}{path}", self.bucket, params=params,
            headers={"Authorization": f"bearer {token}",
                     # Reddit MANDATES this UA shape and throttles generic ones.
                     "User-Agent": config.REDDIT_USER_AGENT})
        if resp is None or resp.status_code >= 400:
            return None
        try:
            return resp.json()
        except ValueError:
            logger.warning("reddit: non-JSON from %s", path)
            return None

    # --- parsing --------------------------------------------------------------

    @staticmethod
    def _signal(child: dict, kind: str) -> Optional[Signal]:
        data = child.get("data") or {}
        name = data.get("name") or ""
        author = (data.get("author") or "").strip()
        sub = data.get("subreddit") or ""
        created = data.get("created_utc")
        if not name or created is None:
            return None
        # A crosspost or a post surfaced from a supply-side sub is a competitor,
        # not a lead. Drop it here so it never reaches the scorer.
        if sub.lower() in {s.lower() for s in config.ANTI_SUBREDDITS}:
            return None

        if kind == "comment":
            title = data.get("link_title") or ""
            body = data.get("body") or ""
        else:
            title = data.get("title") or ""
            body = data.get("selftext") or ""

        return Signal(
            source_uid=f"reddit:{name}",
            platform="reddit",
            source_detail=sub,
            username=author,
            person_key=f"u/{author}@reddit" if author else "",
            permalink="https://www.reddit.com" + (data.get("permalink") or ""),
            post_title=title,
            body=body,
            posted_at=ensure_utc(float(created)),
            signal_type="stated_problem",
            raw={"score": data.get("score"), "kind": kind},
        )

    def _listing(self, path: str, since: datetime, kind: str) -> list[Signal]:
        """Page /new or /comments until we fall out of the window.

        Reddit listings are strictly reverse-chronological, so the first item
        older than `since` means every later item is too — stop, don't keep
        paying for pages we will throw away.
        """
        out: list[Signal] = []
        after = ""
        for _ in range(5):                       # 5 x 100 = 500 items, plenty
            params = {"limit": config.REDDIT_LISTING_LIMIT}
            if after:
                params["after"] = after
            payload = self._get(path, **params)
            if not payload:
                break
            children = (payload.get("data") or {}).get("children") or []
            if not children:
                break

            stop = False
            for child in children:
                sig = self._signal(child, kind)
                if sig is None:
                    continue
                if sig.posted_at < since:
                    stop = True
                    break
                out.append(sig)
            if stop:
                break
            after = (payload.get("data") or {}).get("after") or ""
            if not after:
                break
        return out

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("reddit") or {}
            out = []
            for kind, children in (("post", raw.get("posts", [])),
                                   ("comment", raw.get("comments", []))):
                for child in children:
                    sig = self._signal(child, kind)
                    if sig:
                        out.append(sig)
            return out

        out: list[Signal] = []
        subs = config.SUBS_WEB_DESIGN + config.SUBS_SEO
        for sub in subs:
            out += self._listing(f"/r/{sub}/new", since, "post")
            out += self._listing(f"/r/{sub}/comments", since, "comment")

        # Cross-sub sweep: catches subs that are not on our list at all. A
        # supplement, never the spine — the index lags.
        for query in config.REDDIT_SEARCH_QUERIES:
            payload = self._get("/search", q=query, sort="new", t="day",
                                limit=config.REDDIT_LISTING_LIMIT,
                                type="link")
            if not payload:
                continue
            for child in (payload.get("data") or {}).get("children") or []:
                sig = self._signal(child, "post")
                if sig and sig.posted_at >= since:
                    out.append(sig)

        # De-dup within the run; the DB's UNIQUE(source_uid) catches the rest.
        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())
