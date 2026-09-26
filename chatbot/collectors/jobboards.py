"""Freelance job boards — people who have already decided to pay someone.

This is the purest buying intent in the repo: they are not wondering whether they
need a website, they are choosing who builds it. The tradeoff is competition —
you are bidding against fifty others — and margin. Scored as explicit_hire and
left for the human to judge.

Upwork is ABSENT: its RSS feeds were killed on 2024-08-20 and never restored.
Anything you read online telling you to poll Upwork RSS is out of date.

Freelancer.com's public API serves active projects with no key.
"""

from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("jobboards")


class JobBoardsCollector(Collector):
    name = "jobboards"
    bucket = "jobboards"

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("jobboards") or {}
            out = []
            for p in raw.get("projects", []):
                sig = self._project(p)
                if sig:
                    out.append(sig)
            return out

        out: list[Signal] = []
        for query in config.FREELANCER_QUERIES:
            payload = self.api.get_json(
                config.FREELANCER_API, self.bucket,
                params={"query": query, "limit": 50,
                        "job_details": "true", "full_description": "true"})
            if not payload:
                continue
            projects = ((payload.get("result") or {}).get("projects") or [])
            for project in projects:
                sig = self._project(project)
                if sig and sig.posted_at >= since:
                    out.append(sig)
            logger.info("freelancer.com: %d projects for %r", len(projects), query)
        return out

    @staticmethod
    def _project(project: dict) -> Signal | None:
        pid = project.get("id")
        submit = project.get("time_submitted")
        if not pid or not submit:
            return None
        seo_url = project.get("seo_url") or ""
        budget = project.get("budget") or {}
        currency = (project.get("currency") or {}).get("code", "")
        budget_text = ""
        if budget.get("minimum"):
            budget_text = (f"{currency} {budget.get('minimum')}"
                           f"-{budget.get('maximum', '')}".strip())

        return Signal(
            source_uid=f"freelancer:{pid}",
            platform="jobboards",
            source_detail="freelancer.com",
            post_title=project.get("title") or "",
            body=project.get("description") or project.get("preview_description")
                 or "",
            posted_at=ensure_utc(float(submit)),
            # They are explicitly hiring. This is the top intent tier.
            signal_type="explicit_hire",
            permalink=f"https://www.freelancer.com/projects/{seo_url}"
                      if seo_url else f"https://www.freelancer.com/projects/{pid}",
            # The channel IS the bid — there is no email and never will be.
            contact_channel="bid",
            raw={"budget": budget_text},
        )
