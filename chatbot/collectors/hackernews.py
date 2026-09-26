"""Hacker News — via Algolia (free, no key) plus the Firebase item API.

Two distinct things live here:

1. A keyword sweep over recent comments and stories. Ordinary intent signals.

2. The monthly "Ask HN: Freelancer? Seeking freelancer?" thread, posted on the
   1st. In theory its SEEKING FREELANCER half is businesses stating what they
   need, WITH an email address — which would make it the highest contact-density
   free source for this ICP.

   MEASURED REALITY, AND IT IS BAD: the July 2026 thread had 19 top-level
   comments — 19 SEEKING WORK, 0 SEEKING FREELANCER. It is now essentially all
   supply. The `seeking work` filter below drops every one of them, so this
   collector currently yields close to nothing.

   It is kept because it costs one request, the filter is honest about what it
   throws away, and the thread's composition could change. But do NOT plan your
   pipeline around it, and do not believe anyone (including an earlier version of
   this docstring) who tells you it is 80% emails. It was not checked. It is not.
"""

import re
from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("hackernews")

ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    text = _TAG_RE.sub(" ", html or "")
    return (text.replace("&#x2F;", "/").replace("&quot;", '"')
                .replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<"))


class HackerNewsCollector(Collector):
    name = "hackernews"
    bucket = "hackernews"

    def _hit(self, hit: dict, detail: str) -> Signal | None:
        oid = hit.get("objectID")
        created = hit.get("created_at_i")
        if not oid or not created:
            return None
        body = _strip(hit.get("comment_text") or hit.get("story_text") or "")
        title = hit.get("title") or hit.get("story_title") or ""
        author = hit.get("author") or ""
        emails = EMAIL_RE.findall(body)
        return Signal(
            source_uid=f"hn:{oid}",
            platform="hackernews",
            source_detail=detail,
            username=author,
            person_key=f"{author}@hackernews" if author else "",
            permalink=f"https://news.ycombinator.com/item?id={oid}",
            post_title=title,
            body=body,
            posted_at=ensure_utc(float(created)),
            signal_type="stated_problem",
            email=emails[0] if emails else "",
            contact_channel="email" if emails else "public_reply",
        )

    def _freelancer_thread(self, since: datetime) -> list[Signal]:
        """Find the newest 'Freelancer? Seeking freelancer?' story, then read its
        top-level comments via Firebase."""
        payload = self.api.get_json(
            ALGOLIA, self.bucket,
            params={"tags": "story", "query": config.HN_FREELANCER_QUERY,
                    "hitsPerPage": 3})
        if not payload or not payload.get("hits"):
            return []
        story = payload["hits"][0]
        story_id = story.get("objectID")
        if not story_id:
            return []

        item = self.api.get_json(
            config.HN_FIREBASE.format(id=story_id), self.bucket)
        if not item:
            return []
        kids = (item.get("kids") or [])[:config.HN_MAX_THREAD_ITEMS]
        logger.info("hn: freelancer thread %s has %d top-level comments",
                    story_id, len(kids))

        out: list[Signal] = []
        for kid in kids:
            child = self.api.get_json(
                config.HN_FIREBASE.format(id=kid), self.bucket)
            if not child or child.get("deleted") or child.get("dead"):
                continue
            created = child.get("time")
            if created is None:
                continue
            posted = ensure_utc(float(created))
            if posted < since:
                continue
            body = _strip(child.get("text") or "")
            # The thread's two halves read identically to a keyword matcher.
            # SEEKING FREELANCER = a business that wants to hire. SEEKING WORK =
            # a freelancer advertising, i.e. a competitor. Keep only the former.
            if "seeking work" in body.lower()[:200]:
                continue
            emails = EMAIL_RE.findall(body)
            author = child.get("by") or ""
            out.append(Signal(
                source_uid=f"hn:{kid}",
                platform="hackernews",
                source_detail="Ask HN: Freelancer? Seeking freelancer?",
                username=author,
                person_key=f"{author}@hackernews" if author else "",
                permalink=f"https://news.ycombinator.com/item?id={kid}",
                post_title="Seeking freelancer",
                body=body,
                posted_at=posted,
                signal_type="explicit_hire",   # they are literally hiring
                email=emails[0] if emails else "",
                contact_channel="email" if emails else "public_reply",
            ))
        return out

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("hackernews") or {}
            out = []
            for hit in raw.get("hits", []):
                sig = self._hit(hit, "mock")
                if sig:
                    out.append(sig)
            return out

        out: list[Signal] = []
        cutoff = int(since.timestamp())

        for query in config.HN_QUERIES:
            payload = self.api.get_json(
                ALGOLIA, self.bucket,
                params={"query": query, "tags": "(story,comment)",
                        "numericFilters": f"created_at_i>{cutoff}",
                        "hitsPerPage": 50})
            if not payload:
                continue
            for hit in payload.get("hits", []):
                sig = self._hit(hit, f"search:{query}")
                if sig:
                    out.append(sig)

        out += self._freelancer_thread(since)

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())
