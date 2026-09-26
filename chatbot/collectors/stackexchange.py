"""Stack Exchange — webmasters.stackexchange.com is a room full of buyers.

"Why doesn't my site rank", "how do I get my business on Google", "my WordPress
site is broken and I don't know what I'm doing" — these are people who have a
problem they cannot solve themselves and are one bad afternoon away from paying
someone. Seller contamination is near zero: agencies don't hang around Q&A sites
answering htaccess questions for internet points.

Free, and you already have the key (`STACKEXCHANGE_KEY`), which lifts the quota
from **300/day to 10,000/day**. Verified today: `quota_remaining: 9997`.

TWO RULES THAT ARE NOT OPTIONAL:

1. **The `backoff` field.** Stack Exchange returns `{"backoff": 10}` in the
   response BODY when you are going too fast. Ignoring it does not get you a 429
   — it gets you BLOCKED. It is the only API in this repo that punishes you for
   politely retrying.

2. **The quota is a DAILY budget, not a rate.** When it's gone it's gone until
   tomorrow, so the limiter must SKIP, not sleep (core/ratelimit.py already
   distinguishes these — that's why `RATE_LIMITS["stackexchange"]` carries a
   quota, not just a rate).
"""

import html as html_lib
import re
from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("stackexchange")

API = "https://api.stackexchange.com/2.3/search/advanced"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(body: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", body or "")).strip()


class StackExchangeCollector(Collector):
    name = "stackexchange"
    bucket = "stackexchange"

    def available(self) -> tuple[bool, str]:
        return True, ""      # works keyless at 300/day; the key just lifts it

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("stackexchange") or {}
            return [s for s in (self._item(i, "mock") for i in raw.get("items", []))
                    if s]

        out: list[Signal] = []
        cutoff = int(since.timestamp())

        # NO KEYWORD QUERY, deliberately. webmasters.stackexchange gets about
        # TWO questions a week (measured: `fromdate=-7d` with no query returns
        # 2 items). Adding a keyword on top of that date filter returns zero —
        # which is what a "smart" q= search did, and it looked like the API was
        # broken when in fact the site is just tiny.
        #
        # So we pull EVERY recent question — it is one request and a handful of
        # rows — and let the scorer decide. Filtering a firehose is worth it;
        # filtering a trickle just throws the trickle away.
        for site in config.STACKEXCHANGE_SITES:
            params = {
                "order": "desc",
                "sort": "creation",
                "site": site,
                "fromdate": cutoff,
                "filter": "withbody",
                "pagesize": 100,
            }
            if config.STACKEXCHANGE_KEY:
                params["key"] = config.STACKEXCHANGE_KEY

            payload = self.api.get_json(API, self.bucket, params=params)
            if payload:

                # Not optional. Ignoring `backoff` gets the app blocked, not
                # rate-limited — it is the one API here that punishes a retry.
                backoff = payload.get("backoff")
                if backoff:
                    logger.warning("stackexchange asked for %ss backoff — obeying",
                                   backoff)
                    try:
                        self.api._limiter.penalise(self.bucket, float(backoff))
                    except (TypeError, ValueError):
                        pass

                items = payload.get("items") or []
                for item in items:
                    sig = self._item(item, site)
                    if sig:
                        out.append(sig)

                remaining = payload.get("quota_remaining")
                if remaining is not None and remaining < 100:
                    logger.warning("stackexchange daily quota nearly gone (%s left)",
                                   remaining)

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())

    @staticmethod
    def _item(item: dict, site: str) -> Signal | None:
        qid = item.get("question_id")
        created = item.get("creation_date")
        if not qid or created is None:
            return None
        owner = item.get("owner") or {}
        name = owner.get("display_name") or ""

        return Signal(
            source_uid=f"se:{site}:{qid}",
            platform="stackexchange",
            source_detail=site,
            username=name,
            person_key=f"{name}@stackexchange" if name else "",
            permalink=item.get("link") or "",
            post_title=html_lib.unescape(item.get("title") or ""),
            body=_strip(item.get("body") or "")[:4000],
            posted_at=ensure_utc(float(created)),
            signal_type="stated_problem",
            # There is no email or phone on Stack Exchange, ever. You answer the
            # question in public and they come to you — same motion as Reddit.
            contact_channel="public_reply",
            raw={"tags": item.get("tags"), "answers": item.get("answer_count")},
        )
