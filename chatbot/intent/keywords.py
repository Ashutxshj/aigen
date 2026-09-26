"""Phrase banks.

The whole game is separating BUYERS from SELLERS. On r/SEO the people selling SEO
outnumber the people buying it, and both use the same nouns. A naive keyword
match on "SEO" returns a list of your competitors.

So the banks are asymmetric on purpose: the positive banks are permissive (a lead
is worth a look even if the phrasing is odd) and the HARD_KILL bank is
aggressive (one hit and the row is dead, no LLM call, no second chance). It is
much cheaper to miss a lead than to spend a Gemini call and a human's attention
on a competitor's ad.

Note the inversion from the sibling repos: email-automation/config.py lists "seo"
in EXCLUDED_KEYWORDS because there, an SEO agency is a competitor to filter out.
Here, a person ASKING for SEO is the single best lead we can find. Same word,
opposite meaning, decided entirely by who is speaking.
"""

import re

# --- positive: web design demand ---------------------------------------------

WEB_DESIGN_NEED = [
    "need a website", "need a web site", "want a website", "looking for a website",
    "looking for a web designer", "looking for a web developer",
    "need a web designer", "need a web developer", "hire a web designer",
    "hire a web developer", "hire someone to build", "build me a website",
    "get a website made", "get a website built", "website built for",
    "someone to build my site", "someone to make a website",
    "how do i get a website", "how much does a website cost",
    "how much should a website cost", "website quote", "quote for a website",
    "need an online presence", "no online presence", "get my business online",
    "get online", "need a landing page", "redesign my website",
    "my website is outdated", "my site looks terrible", "website recommendations",
]

NEW_BUSINESS = [
    "starting a business", "started a business", "just started my business",
    "new business", "opening a", "about to open", "about to launch",
    "just registered", "registered my llc", "registered my company",
    "first business", "launching next month", "opening next month",
    "just incorporated", "starting my own", "going out on my own",
    "small business owner", "just bought a domain", "bought a domain",
    "got a domain",
]

NO_SITE = [
    "don't have a website", "dont have a website", "do not have a website",
    "no website yet", "without a website", "only have an instagram",
    "only on instagram", "just a facebook page", "only have a facebook",
    "no site yet", "haven't built a site", "havent built a site",
]

# --- positive: SEO demand -----------------------------------------------------

SEO_NEED = [
    "need seo", "need help with seo", "hire an seo", "hire a seo",
    "looking for an seo", "seo consultant", "seo agency recommendations",
    "not ranking", "not showing up on google", "not showing up in search",
    "can't find my site on google", "cant find my site on google",
    "no traffic to my site", "no one visits my site", "zero traffic",
    "how do i rank", "how to rank on google", "improve my google ranking",
    "google my business", "not on google maps", "maps listing",
    "drop in traffic", "traffic dropped", "lost rankings",
    "how do i show up in search", "get found on google",
]

# --- ownership / budget / help-seeking ----------------------------------------

OWNERSHIP = [
    "my business", "my shop", "my store", "my restaurant", "my salon",
    "my clinic", "my company", "i run a", "i own a", "we're opening",
    "we are opening", "our store", "our business", "my customers",
]

BUDGET = [
    "budget", "how much would", "how much does it cost", "willing to pay",
    "happy to pay", "can pay", "paid gig", "will pay", "quote", "pricing",
    "$", "£", "₹", "€",
]

# An explicit intent to HIRE outranks everything. This is the tier-1 signal.
EXPLICIT_HIRE = [
    "[hiring]", "hiring a", "looking to hire", "want to hire", "need to hire",
    "willing to pay", "paid work", "who can i pay", "someone i can pay",
    "recommend a designer", "recommend an agency", "recommendations for a designer",
]

# --- HARD KILL ----------------------------------------------------------------
#
# One hit and the row is dead. These are ordered by how much damage they do.

# 1. Sellers. The dominant false positive. These people are advertising.
SELLER = [
    "i'm a web developer", "im a web developer", "i am a web developer",
    "i'm a web designer", "im a web designer", "i'm a designer",
    "i'm a freelance", "im a freelance", "i'm an seo", "im an seo",
    "my agency", "our agency",
    # NOT a bare "we offer" / "we provide" / "we specialise". Every trades
    # business on earth describes itself that way: "We are a landscaping company.
    # We offer lawn care... we don't have a website and want to hire a web
    # designer" is a PERFECT lead, and a bare "we offer" hard-killed it — score 0,
    # no LLM, no appeal. Only kill when what they're offering is OUR service.
    "we offer web", "we offer seo", "we offer digital", "we offer marketing",
    "we provide web", "we provide seo", "we specialize in web",
    "we specialise in web", "we specialize in seo", "we specialise in seo",
    "services we offer", "dm me", "pm me", "message me if", "hit me up if",
    "my portfolio", "portfolio:", "check out my work", "here's my work",
    "[for hire]", "for hire", "available for work", "taking on clients",
    "accepting clients", "open for business", "clients i've worked",
    "i build websites", "i make websites", "i do seo", "services i offer",
    "my rates", "my pricing", "free consultation", "free audit",
]

# 2. Retrospectives. "I built my site" is the single most common false positive
#    in the whole corpus: it matches half the web-design vocabulary and is past
#    tense, i.e. the work is DONE and there is nothing to sell.
RETROSPECTIVE_RE = re.compile(
    r"\b(?:i|we)\s+(?:just\s+|finally\s+)?"
    r"(?:built|made|launched|finished|shipped|created|designed|redesigned|"
    r"completed|rebuilt)\b",
    re.I)

# 3. Showcase / feedback requests. Also done, also not buying.
SHOWCASE = [
    "feedback on my", "roast my", "rate my", "check out my", "show hn",
    "just launched", "just shipped", "here's what i learned",
    "what do you think of my", "thoughts on my site", "critique my",
]

# 4. Students, learners, hobbyists. No budget, by definition.
STUDENT = [
    # NOT a bare "learning". "I own a salon and I am learning the hard way that
    # we need a website" is a buyer telling you they are in pain, and a bare
    # "learning" killed it outright. Kill the STUDENT, not the verb.
    "learning to code", "learning web dev", "learning html", "learning css",
    "learning javascript", "learning wordpress", "i'm learning", "im learning",
    "still learning", "teaching myself",
    "bootcamp", "tutorial", "assignment", "homework",
    "college project", "uni project", "school project", "portfolio project",
    "practice project", "i'm studying", "im studying", "self taught",
    "career change", "first project", "junior dev",
]

# 5. No-budget. Explicitly refusing to pay.
NO_BUDGET = [
    "as cheap as possible", "cheapest", "free website", "for free",
    "no budget", "zero budget", "cant afford", "can't afford", "unpaid",
    "exposure", "equity only", "revenue share", "profit share",
]

# 6. Employment posts. A salaried job, not a client.
EMPLOYMENT = [
    "full-time", "full time position", "salary", "w2", "benefits",
    "401k", "remote position", "job opening", "we're hiring a",
]

# 7. Practitioners talking shop. Jargon density = peer, not prospect. A business
#    owner who needs a website does not say "core web vitals".
JARGON = [
    "schema markup", "core web vitals", "htaccess", "canonical tag",
    "robots.txt", "hreflang", "serp volatility", "crawl budget",
    "structured data", "lighthouse score", "cumulative layout shift",
    "server side rendering", "webpack", "next.js", "react", "tailwind",
    "backlink profile", "domain authority", "ahrefs", "semrush", "screaming frog",
]

HARD_KILL_BANKS = {
    "seller": SELLER,
    "showcase": SHOWCASE,
    "student": STUDENT,
    "no_budget": NO_BUDGET,
    "employment": EMPLOYMENT,
    "jargon": JARGON,
}

POSITIVE_BANKS = {
    "web_design_need": (WEB_DESIGN_NEED, 35),
    "seo_need": (SEO_NEED, 35),
    "new_business": (NEW_BUSINESS, 25),
    "ownership": (OWNERSHIP, 15),
    "no_site": (NO_SITE, 10),
    "budget": (BUDGET, 10),
    "explicit_hire": (EXPLICIT_HIRE, 30),
}


# --- proximity patterns -------------------------------------------------------
#
# Literal phrases alone have terrible recall, and the misses are not random —
# they are the BEST leads. Real people write "we need a NEW website", "I need a
# simple 5-page website", "looking to hire someone to build our site". None of
# those contain the literal string "need a website", so a pure phrase match drops
# them. That silently binned the entire Hacker News freelancer thread, which is
# the single highest contact-density source in this repo.
#
# So: a verb of wanting, then up to ~5 words of noise, then the thing wanted.

_WANT = r"(?:need|want|looking for|look for|after|hire|hiring|get|getting|build|" \
        r"buy|shopping for|in the market for|searching for|seeking)"
_NOISE = r"(?:\s+\w+){0,5}?"
_THING = r"(?:web\s?site|website|web designer|web developer|webdesigner|" \
         r"landing page|online store|e-?commerce site|online presence|" \
         r"web presence|homepage)"

NEED_WEBSITE_RE = re.compile(rf"\b{_WANT}\b{_NOISE}\s+(?:a|an|the|our|my|some)?"
                             rf"\s*{_NOISE}\s*\b{_THING}\b", re.I)

_SEO_THING = r"(?:seo|search engine optimi[sz]ation|google ranking|" \
             r"search ranking|google visibility)"
NEED_SEO_RE = re.compile(rf"\b{_WANT}\b{_NOISE}\s+(?:a|an|the|some|help with)?"
                         rf"\s*{_NOISE}\s*\b{_SEO_THING}\b", re.I)

# "someone to build/make/design our site", "somebody who can do our SEO"
SOMEONE_TO_RE = re.compile(
    r"\b(?:someone|somebody|a person|a freelancer|an agency|a company)\s+"
    r"(?:who\s+can\s+|to\s+)"
    r"(?:build|make|design|create|redesign|fix|do|handle|sort)\b", re.I)

# Explicit tags on job/hire boards.
HIRING_TAG_RE = re.compile(r"\[\s*hiring\s*\]|seeking\s+freelancer", re.I)

PROXIMITY = {
    "web_design_need": (NEED_WEBSITE_RE, 35),
    "seo_need": (NEED_SEO_RE, 35),
    "someone_to_build": (SOMEONE_TO_RE, 30),
    "explicit_hire": (HIRING_TAG_RE, 30),
}


def _boundaried(phrase: str) -> re.Pattern:
    """`phrase in text` is WRONG for a phrase bank and it kills real buyers.

    Proven false kills from a plain substring match:
      * "looking for freelancers to build one"  -> NO_BUDGET "for free"  -> 0
      * "the reaction to our new menu"          -> JARGON   "react"      -> 0
    Both are hard kills, so the lead is gone with no LLM call and no appeal.
    Anchor on word boundaries, but only on the ends that ARE word characters —
    "[for hire]" and "portfolio:" have punctuation ends and \b would never match.
    """
    pattern = re.escape(phrase)
    if phrase[:1].isalnum():
        pattern = r"\b" + pattern
    if phrase[-1:].isalnum():
        pattern = pattern + r"\b"
    return re.compile(pattern, re.I)


_COMPILED: dict[str, re.Pattern] = {}


def hits(text: str, bank: list[str]) -> list[str]:
    out = []
    for phrase in bank:
        rx = _COMPILED.get(phrase)
        if rx is None:
            rx = _COMPILED[phrase] = _boundaried(phrase)
        if rx.search(text):
            out.append(phrase)
    return out


# --- language -----------------------------------------------------------------
#
# Every phrase bank above is English, and that is a silent, total filter on the
# rest of the world. A Spanish shop owner writing "necesito una página web para
# mi negocio" hits no bank, scores 0, and score.py drops anything scoring 0
# BEFORE Gemini sees it. The lead is not rejected — it is invisible.
#
# Gemini is perfectly multilingual and would judge that post correctly. It simply
# never gets the chance. So: detect "this is probably not English" and route those
# to the classifier instead of binning them.
#
# The detector is deliberately crude and dependency-free. It does not identify the
# language; it only answers "is this English?", and it is allowed to be wrong in
# the SAFE direction — a false "not English" costs one Gemini slot, while a false
# "English" costs a real lead.

# The commonest English function words. Any real English sentence of a few dozen
# characters contains several.
_ENGLISH_STOPWORDS = {
    "the", "and", "for", "you", "are", "with", "have", "this", "that", "not",
    "but", "can", "from", "your", "was", "would", "should", "could", "will",
    "what", "when", "how", "why", "who", "any", "some", "our", "their", "there",
    "been", "just", "like", "get", "got", "know", "need", "want", "help",
    "about", "than", "them", "they", "were", "does", "did", "has", "had", "its",
    "out", "one", "all", "very", "much", "more", "make", "made", "look", "into",
}

_LATIN_WORD_RE = re.compile(r"[a-z']+")


def looks_english(text: str) -> bool:
    """A cheap 'is this English?', biased towards saying yes.

    Two blunt signals:
      * Script — if most letters are not Latin (Devanagari, Cyrillic, Han,
        Arabic, Thai...), it is certainly not English.
      * Function words — English prose is dense with the/and/for/you. A stretch
        of Latin-script text with almost none of them is Spanish, Portuguese,
        German, Indonesian or romanised Hindi, but it is not English.
    """
    if not text or len(text) < 25:
        # Too short to judge. Call it English so the normal path handles it: we
        # would rather waste nothing than spend a Gemini call on "thanks!".
        return True

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if c.isascii())
    if latin / len(letters) < 0.6:
        return False                       # a different script entirely

    words = _LATIN_WORD_RE.findall(text.lower())
    if len(words) < 8:
        return True                        # not enough words to measure
    stops = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    # Real English runs well above 10% function words. Under 5% across a passage
    # this long is another language wearing the Latin alphabet.
    return (stops / len(words)) >= 0.05
