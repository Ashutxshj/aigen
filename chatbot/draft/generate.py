"""Draft an opener. NEVER send one.

There is no send path in this repo and there must never be one. On Reddit an
automated promotional DM is the fastest way to lose the account permanently, and
the account is the asset — lose it and every future lead on the platform goes
with it. This module writes text into a spreadsheet cell. A human reads it, edits
it, and decides whether to post it.

The opener BRANCHES ON CHANNEL, because these are different genres of writing:

  public_reply  A helpful comment that answers their actual question and earns
                the right to be contacted. It must be useful even if they never
                hire you. A pitch posted as a public Reddit comment gets
                downvoted, reported, and removed — it is strictly worse than
                saying nothing.
  email / bid   A short, specific note. Closer to the /email-automation tone.

And it branches on SERVICE, because "you have no website" and "you have a website
nobody can find" are opposite problems and the wrong one is an instant tell that
you did not read their post.

The validator is ported from email-automation/draft.py, which is the most
valuable thing in that repo. plan.txt learned it the expensive way: "One wrong
claim destroys the credibility that the specificity was supposed to buy."
"""

import re

import config
from core import log
from core.gemini import Gemini, GeminiError
from core.models import Lead

logger = log.get("draft")

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "opener": {"type": "STRING"},
        },
        "required": ["id", "opener"],
    },
}

SYSTEM = """You write the FIRST message from Ashutosh, who runs a small web design
and SEO studio, to somebody who has just publicly said they need help.

You are writing ONE of two things, and the input tells you which:

PUBLIC_REPLY (most common — Reddit, HN, forums):
  A genuinely helpful public comment. Answer the question they actually asked,
  concretely and for free. Give them something they can act on even if they never
  reply to you. ONE short line at the end may mention you do this for a living
  and offer to help — no link, no price, no pitch. If the comment would be
  worthless with that last line removed, it is a bad comment: rewrite it.

EMAIL / BID:
  A short, specific note. Say what you noticed (accurately), say one useful thing,
  ask one question. No pitch deck, no bullet list of services.

ABSOLUTE RULES — breaking any of these makes the draft useless:
  * Use ONLY facts present in the input. Do not invent their business name, their
    location, their traffic, their revenue, or their timeline.
  * NEVER claim to have looked at their website unless a website URL is given. If
    has_website is "no", you have not seen a site, because there is no site.
  * NEVER invent a metric. No "your site loads in 8 seconds", no "you're ranking
    #47", unless that number is in the input.
  * Do not flatter. Do not open with "Hi! I love what you're building!".
  * No emoji. No exclamation marks. No "I hope this finds you well".
  * Sound like a person who read their post, because you did.
  * 40-110 words.
  * WRITE IN THE LANGUAGE THEY WROTE IN. Spanish post, Spanish reply. Hindi post,
    Hindi reply. Answering a Spanish post in English is an instant tell that you
    did not actually read it, and it is the one mistake that guarantees no reply.
"""

# Phrases that assert something we cannot back up. Cheap, blunt, and they catch
# the failure mode that actually happens.
_SITE_CLAIMS = [
    "your website", "your site", "i looked at", "i visited", "i checked out your",
    "i had a look at", "browsing your", "on your homepage", "your landing page",
]
_FLATTERY = ["love what you", "amazing work", "impressive", "hope this finds you",
             "i hope you're well", "great to see"]
_METRIC_RE = re.compile(r"\b\d+(\.\d+)?\s*(seconds?|s\b|ms|%|percent)\b", re.I)
_RANK_RE = re.compile(r"\b(?:rank(?:ing|ed)?|position)\s*#?\s*\d+", re.I)


def validate(opener: str, lead: Lead) -> str | None:
    """Reason the draft is unusable, or None if it is safe to show a human.

    GROUNDEDNESS IS CHECKED FIRST, before style or length. The order matters: a
    draft that is both too short AND invents a fact must report the invented
    fact, because that is the one that loses the lead. Reporting "too short"
    would hide it behind a cosmetic complaint.
    """
    if not opener or not opener.strip():
        return "empty"

    low = opener.lower()

    # 1. The expensive mistake: implying you have seen a site that does not exist.
    if not lead.signal.website:
        for claim in _SITE_CLAIMS:
            if claim in low:
                return (f"claims to have seen a site that we have no URL for "
                        f"({claim!r})")

    # 2. A number we did not measure is a number we cannot defend. plan.txt:
    #    "One wrong claim destroys the credibility that the specificity was
    #    supposed to buy."
    source = (lead.signal.text() + " "
              + str(lead.signal.raw.get("author_context", ""))).lower()
    metric = _METRIC_RE.search(low)
    if metric and metric.group(0).lower() not in source:
        return f"invents a metric ({metric.group(0)!r})"
    rank = _RANK_RE.search(low)
    if rank and rank.group(0).lower() not in source:
        return f"invents a ranking ({rank.group(0)!r})"

    # 3. A public reply that opens by pitching is the one that gets you banned.
    if lead.signal.contact_channel == "public_reply":
        if low.strip().startswith(("i run a", "i'm a web", "im a web",
                                   "i own a web", "we're an agency")):
            return "public reply opens by pitching itself"

    # 4. Tone.
    for phrase in _FLATTERY:
        if phrase in low:
            return f"flattery ({phrase!r})"
    if "!" in opener:
        return "exclamation mark"

    # 5. Length last — the least important thing that can be wrong with it.
    words = len(opener.split())
    if words < config.OPENER_MIN_WORDS:
        return f"too short ({words} words)"
    if words > config.OPENER_MAX_WORDS + 40:
        return f"too long ({words} words)"

    return None


def _prompt(leads: list[Lead], attempt: int = 0) -> str:
    parts = []
    if attempt:
        # WITHOUT THIS LINE REGENERATION IS A NO-OP. gemini.structured() caches on
        # a hash of (system + user), so re-sending the identical prompt for a
        # rejected batch just replays the SAME rejected draft out of llm_cache —
        # REGEN_ROUNDS burned two rounds and never re-asked the model once.
        parts.append(
            f"REWRITE (attempt {attempt + 1}): the previous draft for these was "
            "rejected by a groundedness check. Do not claim to have seen a site, "
            "do not invent numbers, do not flatter, no exclamation marks. Use "
            "only what is written below.\n")
    for lead in leads:
        s = lead.signal
        v = lead.verdict
        parts.append(
            f"ID: {s.source_uid}\n"
            f"CHANNEL: {s.contact_channel or 'public_reply'}\n"
            f"SERVICE_WANTED: {v.service_wanted or 'unknown'}\n"
            f"HAS_WEBSITE: {'yes' if s.website else 'no'}\n"
            f"WEBSITE: {s.website or '(none known)'}\n"
            f"BUSINESS: {v.business_type or '(unknown)'}\n"
            f"THEIR_PROBLEM: {v.stated_problem or '(not stated)'}\n"
            f"WHERE: {s.platform}/{s.source_detail}\n"
            f"WHAT THEY WROTE:\n{s.text()[:900]}\n"
            f"THEIR RECENT POSTS:\n{s.raw.get('author_context', '')[:600]}\n"
            f"---")
    return "\n".join(parts)


def draft_all(leads: list[Lead], gemini: Gemini, store) -> int:
    """Draft an opener for each lead. Returns how many were written."""
    if not leads:
        return 0

    if not getattr(gemini, "enabled", True):
        # No key: say so once, mark every row for a human, and do NOT invent a
        # draft that reads as if a model wrote it.
        logger.warning("no Gemini key: %d openers must be written by hand",
                       len(leads))
        for lead in leads:
            channel = lead.signal.contact_channel or "public_reply"
            store.save_draft(lead.signal.source_uid, "", channel,
                             "needs_manual: no GEMINI_API_KEY")
            lead.draft_status = "needs_manual: no GEMINI_API_KEY"
        return 0

    pending = list(leads)
    written = 0

    for attempt in range(config.REGEN_ROUNDS + 1):
        if not pending:
            break
        rejected: list[Lead] = []

        for i in range(0, len(pending), config.GEMINI_BATCH_SIZE):
            batch = pending[i:i + config.GEMINI_BATCH_SIZE]
            try:
                items = gemini.structured(SYSTEM, _prompt(batch, attempt), SCHEMA)
            except GeminiError as exc:
                logger.error("drafting failed for a batch of %d: %s",
                             len(batch), exc)
                for lead in batch:
                    store.save_draft(lead.signal.source_uid, "", "",
                                     "needs_manual: model unavailable")
                continue

            by_id = {it.get("id"): it.get("opener", "")
                     for it in items if isinstance(it, dict)}
            for lead in batch:
                opener = (by_id.get(lead.signal.source_uid) or "").strip()
                why = validate(opener, lead)
                channel = lead.signal.contact_channel or "public_reply"
                if why is None:
                    store.save_draft(lead.signal.source_uid, opener, channel, "ok")
                    lead.opener, lead.opener_channel = opener, channel
                    lead.draft_status = "ok"
                    written += 1
                elif attempt < config.REGEN_ROUNDS:
                    logger.debug("regenerating %s: %s",
                                 lead.signal.source_uid, why)
                    rejected.append(lead)
                else:
                    # Never show a human a draft we know is wrong. Tell them to
                    # write this one by hand.
                    logger.warning("%s: rejected after %d rounds — %s",
                                   lead.signal.source_uid,
                                   config.REGEN_ROUNDS + 1, why)
                    store.save_draft(lead.signal.source_uid, "", channel,
                                     f"needs_manual: {why}")
                    lead.draft_status = f"needs_manual: {why}"

        pending = rejected

    return written
