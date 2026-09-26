"""Reddit WITHOUT an account, without an app, without a client id.

Why this exists: the OAuth collector (reddit.py) needs a "script" app, which you
create while logged in. It is read-only and cannot post as you — but if that
account is the only one you have left, "essentially zero risk" is not the same as
"no risk", and there is no reason to take any.

Reddit's own unauthenticated endpoints are dead: www.reddit.com/r/x/new.json and
old.reddit.com both return **403 Blocked** from a datacenter or a plain script UA
(verified 2026-07-11). Anything on the internet telling you to just append .json
is out of date.

What still works is **Arctic Shift** — the public Reddit archive that replaced
Pushshift after it was restricted to moderators. No auth, no key, no account.

  https://arctic-shift.photon-reddit.com/api/posts/search
  https://arctic-shift.photon-reddit.com/api/comments/search

Measured freshness (2026-07-11), which is the only thing that matters for a 48h
window:

  r/smallbusiness  newest post     0.1h old
  r/Handyman       newest post     1.2h old
  r/Contractor     newest post     4.7h old
  r/Handyman       newest COMMENT  0.0h old

So it is effectively live, and it gives you COMMENTS — which is where roughly a
third of "I need a website" intent actually lives (buried in a weekly megathread,
never its own post). The OAuth path gives you nothing here that this does not.

The honest tradeoffs:
  * It is a community-run archive. It can go down. If it does, this collector logs
    a warning and the run continues on the other sources — it must never be the
    single point of failure for the whole tool.
  * Ingest lag is minutes-to-hours, not seconds. For the trade subs we target
    (r/Contractor gets a handful of comments per thread) that is fine — you are
    aiming to be in the first five comments, not the first.
  * Be polite. It is a free service run by one person. We rate-limit ourselves
    hard and send a descriptive UA with a contact address.
"""

from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("reddit_public")

POSTS = "https://arctic-shift.photon-reddit.com/api/posts/search"
COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"


class RedditPublicCollector(Collector):
    name = "reddit"                # same platform id, so dedup/scoring are shared
    bucket = "arcticshift"

    def available(self) -> tuple[bool, str]:
        return True, ""            # no credentials of any kind

    # --- parsing -------------------------------------------------------------

    @staticmethod
    def _signal(item: dict, kind: str) -> Signal | None:
        rid = item.get("id")
        created = item.get("created_utc")
        sub = item.get("subreddit") or ""
        author = (item.get("author") or "").strip()
        if not rid or created is None:
            return None

        # A post surfaced from a supply-side sub is a competitor, not a lead.
        if sub.lower() in {s.lower() for s in config.ANTI_SUBREDDITS}:
            return None

        if kind == "comment":
            prefix, title = "t1_", (item.get("link_title") or "")
            body = item.get("body") or ""
            link = item.get("permalink") or ""
        else:
            prefix, title = "t3_", (item.get("title") or "")
            body = item.get("selftext") or ""
            link = item.get("permalink") or ""

        if body in ("[deleted]", "[removed]"):
            return None

        permalink = ("https://www.reddit.com" + link if link.startswith("/")
                     else link or f"https://www.reddit.com/comments/{rid}")

        return Signal(
            source_uid=f"reddit:{prefix}{rid}",
            platform="reddit",
            source_detail=sub,
            username=author,
            person_key=f"u/{author}@reddit" if author else "",
            permalink=permalink,
            post_title=title,
            body=body,
            posted_at=ensure_utc(float(created)),
            signal_type="stated_problem",
            raw={"score": item.get("score"), "kind": kind, "via": "arctic-shift"},
        )

    def _search(self, url: str, sub: str, since: datetime,
                kind: str) -> list[Signal]:
        payload = self.api.get_json(
            url, self.bucket,
            params={
                "subreddit": sub,
                "after": int(since.timestamp()),
                "limit": 100,
                "sort": "desc",
            },
            headers={"User-Agent": config.API_USER_AGENT})
        if not payload:
            return []
        items = payload.get("data") or []
        out = []
        for item in items:
            sig = self._signal(item, kind)
            if sig:
                out.append(sig)
        return out

    # --- fetch ---------------------------------------------------------------

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("reddit") or {}
            out = []
            for kind, key in (("post", "posts"), ("comment", "comments")):
                for child in raw.get(key, []):
                    # The fixture is in Reddit's own {"data": {...}} envelope;
                    # Arctic Shift returns the object flat. Unwrap either.
                    item = child.get("data", child)
                    item = dict(item)
                    item.setdefault("id", str(item.get("name", ""))[3:])
                    sig = self._signal(item, kind)
                    if sig:
                        out.append(sig)
            return out

        out: list[Signal] = []
        subs = config.SUBS_WEB_DESIGN + config.SUBS_SEO
        for sub in subs:
            posts = self._search(POSTS, sub, since, "post")
            # Comments matter as much as posts here: a large share of "I need a
            # website" intent is a reply inside a weekly thread and never becomes
            # a post of its own. A post-only collector silently misses all of it.
            comments = self._search(COMMENTS, sub, since, "comment")
            if posts or comments:
                logger.debug("r/%s: %d posts, %d comments",
                             sub, len(posts), len(comments))
            out += posts + comments

        if not out:
            logger.warning(
                "arctic-shift returned nothing for any subreddit. It is a "
                "community-run archive and it may be down — check "
                "https://arctic-shift.photon-reddit.com before assuming there "
                "were simply no leads today.")

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())
