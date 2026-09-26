"""Forums — Discourse instances and Lobsters. Free, no key, no card.

This is the collector that does the job Google search was supposed to do, and it
does it better: instead of asking a search engine to *find* the forum threads, we
ask the forums directly. Discourse ships a public `/search.json` on every
instance, and thousands of communities run Discourse.

Why forums matter more than their traffic suggests: a platform support forum is a
**near-pure buyer population**. Someone posting on the Shopify or WordPress
community has already paid for the platform, is stuck, and the sentence "is there
someone I can just pay to do this?" appears constantly. Almost no agencies lurk
there — there is no karma to farm and no audience to build, so the seller
contamination that ruins r/SEO is simply absent.

Adding a new forum is one line in `config.DISCOURSE_SITES`, not a new file.

Note on robots.txt: `/search.json` is an API endpoint and Discourse serves it
freely, but we still route through the API client with a conservative bucket.
These are small communities, often self-hosted by volunteers. Do not hammer them.
"""

from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("forums")


class ForumsCollector(Collector):
    name = "forums"
    bucket = "feeds"

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("forums") or {}
            out = []
            for t in raw.get("topics", []):
                sig = self._topic(t, "mock", "mock")
                if sig:
                    out.append(sig)
            return out

        out: list[Signal] = []

        # THE FRESHNESS TRAP, and it is the same one Google's dateRestrict solves.
        # Discourse search sorts by RELEVANCE, not recency. A plain search for
        # "hire someone" on community.shopify.com returns, as its top hits,
        # threads that are 603 and 1,212 DAYS OLD — titles that look perfect
        # ("Hire someone for help with Shopify store") attached to people who
        # hired somebody three years ago. Measured, not guessed.
        #
        # `after:YYYY-MM-DD order:latest` is what makes this collector work at
        # all. Drop those two operators and you get a beautiful, useless list.
        after = since.strftime("%Y-%m-%d")

        for base in config.DISCOURSE_SITES:
            host = base.split("//", 1)[-1].strip("/")
            for query in config.DISCOURSE_QUERIES:
                payload = self.api.get_json(
                    f"{base}/search.json", self.bucket,
                    params={"q": f"{query} after:{after} order:latest"})
                if not payload:
                    continue

                # Discourse returns `topics` (the thread) and `posts` (the bodies)
                # as separate lists joined by topic_id. Neither alone is enough:
                # topics have the title, posts have the words.
                bodies = {p.get("topic_id"): p.get("blurb") or ""
                          for p in (payload.get("posts") or [])}
                topics = payload.get("topics") or []
                for topic in topics:
                    sig = self._topic(topic, host, base,
                                      bodies.get(topic.get("id"), ""))
                    if sig and sig.posted_at >= since:
                        out.append(sig)
                logger.debug("%s %r -> %d topics", host, query, len(topics))

        out += self._lobsters(since)

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())

    @staticmethod
    def _topic(topic: dict, host: str, base: str, body: str = "") -> Signal | None:
        tid = topic.get("id")
        created = topic.get("created_at")
        title = topic.get("title") or topic.get("fancy_title") or ""
        if not tid or not created or not title:
            return None
        slug = topic.get("slug") or ""
        return Signal(
            source_uid=f"discourse:{host}:{tid}",
            platform="forums",
            source_detail=host,
            permalink=f"{base}/t/{slug}/{tid}" if base != "mock" else "",
            post_title=title,
            body=body,
            posted_at=ensure_utc(created),
            signal_type="stated_problem",
            contact_channel="public_reply",
        )

    def _lobsters(self, since: datetime) -> list[Signal]:
        payload = self.api.get_json("https://lobste.rs/newest.json", self.bucket)
        if not payload:
            return []
        out = []
        for item in payload if isinstance(payload, list) else []:
            sid = item.get("short_id")
            created = item.get("created_at")
            if not sid or not created:
                continue
            author = (item.get("submitter_user") or {})
            handle = (author.get("username") if isinstance(author, dict)
                      else str(author)) or ""
            sig = Signal(
                source_uid=f"lobsters:{sid}",
                platform="forums",
                source_detail="lobste.rs",
                username=handle,
                person_key=f"{handle}@lobsters" if handle else "",
                permalink=item.get("comments_url") or item.get("url") or "",
                post_title=item.get("title") or "",
                body=item.get("description") or "",
                posted_at=ensure_utc(created),
                signal_type="stated_problem",
                contact_channel="public_reply",
            )
            if sig.posted_at >= since:
                out.append(sig)
        return out
