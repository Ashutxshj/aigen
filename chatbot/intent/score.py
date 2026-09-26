"""Scoring: cheap rules first, Gemini only where the rules are genuinely unsure.

Three tiers, and the order matters for cost:

  Tier 0  hard gates      free, drops most of the corpus
  Tier 1  rule score      free, decides the confident cases at both ends
  Tier 2  Gemini          only the borderline band (BORDERLINE_LOW..HIGH)

The rule score also survives on its own. If Gemini is down or unkeyed, every
lead still gets a rule score and the run still produces a sheet — a model outage
must never look like "no leads today", which is exactly the failure-looks-like-
success trap the sibling repos fall into.
"""

from datetime import datetime

import config
from core import log
from core.gemini import Gemini, GeminiError
from core.models import Lead, Signal, Verdict
from intent import keywords as kw

logger = log.get("score")

CLASSIFY_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "is_lead": {"type": "BOOLEAN"},
            "is_seller": {"type": "BOOLEAN"},
            "role": {"type": "STRING",
                     "enum": ["buyer", "seller", "peer", "student", "promoter",
                              "unclear"]},
            "tense": {"type": "STRING",
                      "enum": ["needs_now", "researching", "already_done",
                               "unclear"]},
            "service_wanted": {"type": "STRING",
                               "enum": ["web_design", "seo", "both", "none"]},
            "business_type": {"type": "STRING"},
            "business_stage": {"type": "STRING"},
            "stated_problem": {"type": "STRING"},
            "budget_signal": {"type": "STRING"},
            "region": {"type": "STRING"},
            "country": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "intent_score_llm": {"type": "INTEGER"},
        },
        "required": ["id", "is_lead", "is_seller", "role", "tense",
                     "service_wanted", "intent_score_llm"],
    },
}

SYSTEM = """You triage public posts for a web-design and SEO agency.

Your ONE job is to tell a BUYER from a SELLER. This is hard because they use the
same words. A person who says "SEO" might be a shop owner who cannot be found on
Google (a buyer) or an agency advertising SEO services (a seller). Get this wrong
and you waste the agency's time pitching a competitor.

  buyer     — owns or is starting a business, wants a website or SEO help.
  seller    — offers web/SEO services. Agency, freelancer, [FOR HIRE].
  peer      — a developer or SEO discussing technique. Not buying.
  student   — learning, coursework, no budget.
  promoter  — dropping a link, self-promoting something unrelated.

tense: needs_now (wants it now) / researching (thinking about it) /
already_done (past tense — "I built my site" — nothing to sell).

SOME POSTS ARE NOT IN ENGLISH. Judge them exactly the same way — a Spanish,
Hindi, German or Indonesian shop owner asking for a website is just as good a
lead as an English one. Write business_type and stated_problem in ENGLISH so the
spreadsheet stays readable, but do not penalise a post for its language.

Rules:
  * Judge ONLY from the text given. Do not guess or embellish.
  * stated_problem must be a short paraphrase OF THEIR OWN WORDS. If they did not
    state a problem, leave it empty. Never invent one.
  * If unsure, role="unclear" and a low score. A false negative costs nothing; a
    false positive costs the agency a wasted pitch and their reputation.
  * intent_score_llm 0-100: how likely is this person to pay someone for a website
    or SEO in the next month.
"""


# --- tier 0: hard gates -------------------------------------------------------

_BOT_AUTHORS = {"automoderator", "[deleted]", "[removed]", "bot"}

# Platforms where a post HAS an author. An OSM business, a newly-registered
# domain and a Freelancer.com project have no username by construction — an
# empty author there is normal, not a deleted account. Checking every platform
# for a missing author silently binned every contactable lead in the sheet,
# which is the exact opposite of what the directory collectors are for.
_AUTHORED = {"reddit", "hackernews", "bluesky", "mastodon", "lobsters"}


def gate(signal: Signal, since: datetime) -> str | None:
    """Reason to drop this signal outright, or None to keep it."""
    if signal.posted_at < since:
        return "outside the window"
    if signal.platform in _AUTHORED:
        author = signal.username.lower().strip()
        if not author or author in _BOT_AUTHORS:
            return "bot/deleted author"
    if signal.source_detail.lower() in {s.lower()
                                        for s in config.ANTI_SUBREDDITS}:
        return f"supply-side source ({signal.source_detail})"
    if signal.signal_type != "structural" and len(signal.text()) < 40:
        return "too short to judge"
    return None


# --- tier 1: rules ------------------------------------------------------------

def rule_score(signal: Signal) -> tuple[int, list[str], str]:
    """(score, which phrases fired, intent_tier). A hard-kill returns 0."""
    text = signal.text()

    for name, bank in kw.HARD_KILL_BANKS.items():
        hit = kw.hits(text, bank)
        if hit:
            return 0, [f"kill:{name}:{hit[0]}"], ""

    if kw.RETROSPECTIVE_RE.search(text):
        # "I built my site" — past tense. The work is done; there is nothing to
        # sell. This is the most common false positive in the whole corpus.
        return 0, ["kill:retrospective"], ""

    if signal.signal_type == "structural":
        # Nobody asked for anything. Real signal, but it is a guess, and it must
        # never be allowed to look like an ask.
        return 45, ["structural"], "structural"

    score = 0
    fired: list[str] = []
    scored_banks: set[str] = set()

    # Proximity patterns first — they catch the phrasings real people actually
    # use ("we need a NEW website", "someone who can build our site") that a
    # literal phrase list misses.
    for name, (pattern, points) in kw.PROXIMITY.items():
        match = pattern.search(text)
        if match:
            score += points
            scored_banks.add(name)
            fired.append(f"{name}~:{match.group(0)[:40].strip()}")

    for name, (bank, points) in kw.POSITIVE_BANKS.items():
        hit = kw.hits(text, bank)
        if hit:
            # Don't pay twice for the same idea: if the proximity regex already
            # scored "web_design_need", the literal phrase adds evidence, not
            # points.
            if name not in scored_banks:
                score += points
                scored_banks.add(name)
            fired.append(f"{name}:{hit[0]}")

    # A question in the title is a person asking for help, not announcing.
    title = signal.post_title.lower().strip()
    if title.endswith("?") or title.split(" ")[0] in {
            "how", "what", "where", "should", "can", "is", "any", "does"}:
        score += 5
        fired.append("help_seeking_form")

    tier = ("explicit_hire" if any(f.startswith("explicit_hire") for f in fired)
            else "stated_problem" if score else "")

    prior = config.SUBREDDIT_PRIORS.get(signal.source_detail, 1.0)
    if prior != 1.0:
        fired.append(f"prior:{signal.source_detail}:{prior}")
    return min(100, int(score * prior)), fired, tier


# --- tier 2: Gemini -----------------------------------------------------------

def _prompt(signals: list[Signal]) -> str:
    parts = []
    for s in signals:
        parts.append(
            f"ID: {s.source_uid}\n"
            f"WHERE: {s.platform}/{s.source_detail}\n"
            f"TITLE: {s.post_title}\n"
            f"BODY: {s.body[:1200]}\n---")
    return "\n".join(parts)


def classify(signals: list[Signal], gemini: Gemini) -> dict[str, dict]:
    """source_uid -> the model's verdict. Batched, cached, never fatal."""
    out: dict[str, dict] = {}
    if not getattr(gemini, "enabled", True):
        # No key. The rule scores stand and the buyer/seller call is not made —
        # which is a WARNING, not a fabricated verdict.
        logger.warning("no Gemini key: %d borderline signals keep their rule "
                       "score and were NOT checked for buyer-vs-seller",
                       len(signals))
        return out
    for i in range(0, len(signals), config.GEMINI_BATCH_SIZE):
        batch = signals[i:i + config.GEMINI_BATCH_SIZE]
        try:
            items = gemini.structured(SYSTEM, _prompt(batch), CLASSIFY_SCHEMA)
        except GeminiError as exc:
            # Do NOT let this look like "no leads". The rule score stands.
            logger.error("classifier failed for a batch of %d — keeping rule "
                         "scores only: %s", len(batch), exc)
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                out[item["id"]] = item
    return out


def _fallback_service(lead: Lead) -> str:
    """service_wanted when the LLM did not (or could not) set one.

    The sheet drops any row whose Service Wanted is "none" — the user cannot
    pitch what he cannot name. Only Gemini sets the field, so without this
    fallback a model outage would set every row to "none" and empty the sheet,
    which is exactly the failure-looks-like-success trap this repo exists to
    avoid. Derive it from the phrase banks that actually fired instead: they
    are the poster's own words.
    """
    fired = {f.split(":")[0].rstrip("~") for f in lead.intent_signals}
    web = bool(fired & {"web_design_need", "someone_to_build", "no_site"})
    seo = "seo_need" in fired
    if web and seo:
        return "both"
    if seo:
        return "seo"
    if web:
        return "web_design"
    if lead.signal.signal_type == "structural":
        # An OSM business that survived the website check: no site IS the pitch.
        return "web_design"
    return "none"


# --- orchestration ------------------------------------------------------------

def score_all(signals: list[Signal], since: datetime, gemini: Gemini,
              store) -> list[Lead]:
    kept: list[Lead] = []
    borderline: list[Signal] = []
    staged: dict[str, Lead] = {}
    foreign = 0

    for sig in signals:
        why = gate(sig, since)
        if why:
            logger.debug("drop %s: %s", sig.source_uid, why)
            continue

        rule, fired, tier = rule_score(sig)
        lead = Lead(signal=sig, score_rule=rule, score=rule,
                    intent_signals=fired, intent_tier=tier)

        if rule == 0:
            # A zero can mean two very different things.
            #
            #   1. A hard-kill fired — a seller, a student, a retrospective. That
            #      is a real judgement and the row is dead.
            #   2. NOTHING fired. Every phrase bank in this repo is English, so a
            #      Spanish shop owner writing "necesito una pagina web para mi
            #      negocio" scores 0 for the sole reason that we cannot read them.
            #
            # Case 2 used to be dropped here, silently, and it made every
            # non-English buyer on the planet invisible. Gemini is multilingual
            # and would judge that post perfectly well — it just never got asked.
            # So a zero with no kill, in a language we do not speak, goes to the
            # classifier instead of the bin.
            killed = any(f.startswith("kill:") for f in fired)
            if (not killed
                    and foreign < config.MAX_FOREIGN_TO_CLASSIFY
                    and not kw.looks_english(sig.text())):
                foreign += 1
                lead.intent_signals = fired + ["non_english"]
                staged[sig.source_uid] = lead
                borderline.append(sig)
                continue
            logger.debug("kill %s: %s", sig.source_uid, fired)
            continue

        staged[sig.source_uid] = lead
        if config.BORDERLINE_LOW <= rule <= config.BORDERLINE_HIGH:
            borderline.append(sig)

    if foreign:
        # Say it out loud. This costs Gemini quota, and a silent cost is how you
        # blow a free tier without knowing why.
        logger.info("routed %d non-English signals to the classifier "
                    "(cap %d) — the English phrase banks scored them 0",
                    foreign, config.MAX_FOREIGN_TO_CLASSIFY)

    if borderline:
        logger.info("asking the classifier about %d borderline signals "
                    "(%d decided by rules alone)",
                    len(borderline), len(staged) - len(borderline))
        verdicts = classify(borderline, gemini)
        for uid, raw in verdicts.items():
            lead = staged.get(uid)
            if lead is None:
                continue
            lead.verdict = Verdict(
                is_lead=bool(raw.get("is_lead")),
                is_seller=bool(raw.get("is_seller")),
                role=raw.get("role", "unclear"),
                tense=raw.get("tense", "unclear"),
                service_wanted=raw.get("service_wanted", "none"),
                business_type=raw.get("business_type", ""),
                business_stage=raw.get("business_stage", ""),
                stated_problem=raw.get("stated_problem", ""),
                budget_signal=raw.get("budget_signal", ""),
                region=raw.get("region", ""),
                country=raw.get("country", ""),
                confidence=float(raw.get("confidence") or 0.0))
            lead.score_llm = int(raw.get("intent_score_llm") or 0)
            lead.score = int(config.RULE_WEIGHT * lead.score_rule +
                             config.LLM_WEIGHT * lead.score_llm)

    for lead in staged.values():
        v = lead.verdict
        # The buyer/seller axis overrides the score outright. A seller with a
        # high keyword score is still a seller.
        if v.role in {"seller", "peer", "student", "promoter"}:
            logger.debug("drop %s: classifier says %s",
                         lead.signal.source_uid, v.role)
            continue
        if v.tense == "already_done":
            logger.debug("drop %s: past tense", lead.signal.source_uid)
            continue
        if v.service_wanted == "none":
            v.service_wanted = _fallback_service(lead)
        store.save_score(lead)
        kept.append(lead)

    kept.sort(key=lambda l: (l.score, l.signal.posted_at), reverse=True)
    return kept
