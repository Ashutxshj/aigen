"""Pydantic models. Every datetime here is timezone-aware UTC, enforced by a
validator — a naive datetime silently breaks the 48h window, which is the single
most likely bug in this whole build.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    """The ONLY way this codebase gets the current time."""
    return datetime.now(timezone.utc)


def ensure_utc(value: Any) -> datetime:
    """Coerce anything date-ish into an aware UTC datetime. Raises on naive
    input rather than guessing a timezone: guessing is how the window breaks."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        value = datetime.fromisoformat(text)
    if not isinstance(value, datetime):
        raise TypeError(f"not a datetime: {value!r}")
    if value.tzinfo is None:
        raise ValueError(
            f"naive datetime {value!r} — every datetime in this codebase must "
            "be timezone-aware UTC")
    return value.astimezone(timezone.utc)


Role = Literal["buyer", "seller", "peer", "student", "promoter", "unclear"]
Tense = Literal["needs_now", "researching", "already_done", "unclear"]
Service = Literal["web_design", "seo", "both", "none"]
SignalType = Literal["explicit_hire", "stated_problem", "structural"]


class Signal(BaseModel):
    """One raw thing somebody said (or one structural fact), before scoring."""

    # source_uid is the PRIMARY dedup key: "reddit:t3_1abc2d", "hn:38472910".
    source_uid: str
    platform: str
    source_detail: str = ""          # subreddit / thread / feed name
    username: str = ""
    person_key: str = ""             # "u/foo@reddit" — for author cooldown
    permalink: str = ""
    post_title: str = ""
    body: str = ""
    posted_at: datetime
    collected_at: datetime = Field(default_factory=utcnow)
    signal_type: SignalType = "stated_problem"

    # Contact / geo, filled by collectors that have them and by enrich/.
    phone: str = ""
    email: str = ""
    website: str = ""
    region: str = ""
    country: str = ""
    geo_method: str = ""             # how region/country was derived
    business_type: str = ""
    contact_channel: str = ""        # email|phone|dm|public_reply|bid|form

    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("posted_at", "collected_at", mode="before")
    @classmethod
    def _utc(cls, v: Any) -> datetime:
        return ensure_utc(v)

    def age_hours(self, now: Optional[datetime] = None) -> float:
        return ((now or utcnow()) - self.posted_at).total_seconds() / 3600.0

    def text(self) -> str:
        return f"{self.post_title}\n{self.body}".strip()


class Verdict(BaseModel):
    """What the classifier (rules and/or Gemini) concluded about a Signal."""

    is_lead: bool = False
    is_seller: bool = False
    role: Role = "unclear"
    tense: Tense = "unclear"
    service_wanted: Service = "none"
    business_type: str = ""
    business_stage: str = ""
    stated_problem: str = ""
    budget_signal: str = ""
    region: str = ""
    country: str = ""
    confidence: float = 0.0


class Lead(BaseModel):
    """A scored Signal that survived the gates. This is what gets exported."""

    signal: Signal
    score_rule: int = 0
    score_llm: int = 0
    score: int = 0
    intent_tier: str = ""            # explicit_hire / stated_problem / structural
    intent_signals: list[str] = Field(default_factory=list)  # phrases that fired
    verdict: Verdict = Field(default_factory=Verdict)
    opener: str = ""
    opener_channel: str = ""         # public_reply / email / bid / phone
    draft_status: str = ""
    other_profiles: str = ""
