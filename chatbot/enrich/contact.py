"""Pull a contact out of a post, and work out where the person actually is.

Read this before you get your hopes up about the phone/email columns:

  Reddit / Bluesky / Mastodon    ~1-2% expose an email. ~0% a phone.
  Hacker News (freelancer thread) ~80% include an email — the thread's format
                                  asks for one. This is the exception.
  Freelance boards                No contact, ever. The bid IS the channel.
  OSM / directories               ~70% phone. But no intent.
  New domains                     WHOIS is redacted post-GDPR. No contact.

So for most intent leads the deliverable is the PERMALINK and the username, and
the outreach is a public reply. That is not a gap in this module — it is the
shape of the data, and the drafting stage is built around it. Anyone promising
you emails for Reddit users is selling you something.
"""

import re

from core import log

logger = log.get("contact")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
# Deliberately conservative. A loose phone regex matches order numbers, prices,
# dates and zip codes, and a wrong phone number in a cold call is worse than none.
PHONE_RE = re.compile(
    r"(?:(?<=\s)|^)(\+?\d{1,3}[\s.-]?)?(\(?\d{3,5}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}"
    r"(?=\s|$|\.|,)")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)

# Junk addresses harvested from template sites — never real.
JUNK_LOCALPARTS = {"example", "email", "youremail", "name", "info@example",
                   "test", "sample", "user", "someone", "noreply", "no-reply"}
JUNK_DOMAINS = {"example.com", "example.org", "domain.com", "yourdomain.com",
                "email.com", "sentry.io", "wixpress.com", "schema.org",
                "w3.org", "gravatar.com"}

# Hosts that are never the lead's own site.
SOCIAL_HOSTS = ("reddit.com", "redd.it", "imgur.com", "youtube.com", "youtu.be",
                "twitter.com", "x.com", "facebook.com", "instagram.com",
                "linkedin.com", "tiktok.com", "github.com", "medium.com",
                "news.ycombinator.com", "wikipedia.org", "google.com")

# --- geography ----------------------------------------------------------------
#
# Precedence matters and is recorded in geo_method, so you can see how much to
# trust the country before you use it in a pitch.

_ENTITY_SUFFIX = [
    (r"\bpvt\.?\s*ltd\b|\bprivate limited\b", "IN"),
    (r"\bllp\b", "IN"),
    (r"\bltd\b|\blimited\b", "GB"),
    (r"\bllc\b|\binc\.?\b|\bcorp\b", "US"),
    (r"\bgmbh\b", "DE"),
    (r"\bpty\s*ltd\b", "AU"),
    (r"\bb\.?v\.?\b", "NL"),
]

_CURRENCY_TAX = [
    (r"£|\bvat\b|\bhmrc\b|\bcompanies house\b|\bltd\b", "GB"),
    (r"₹|\bgst\b|\brupees?\b|\blakh\b|\bcrore\b|\bmca\b", "IN"),
    (r"\bein\b|\bllc\b|\bsales tax\b|\bw2\b|\bs-?corp\b", "US"),
    (r"\babn\b|\bacn\b|\bausindustry\b", "AU"),
    (r"\bcra\b|\bgst/hst\b", "CA"),
    (r"€|\bvat number\b", "EU"),
]

_SUB_COUNTRY = {
    "smallbusinessuk": "GB", "ukpersonalfinance": "GB", "unitedkingdom": "GB",
    "australia": "AU", "ausbusiness": "AU",
    "canadasmallbusiness": "CA",
    "indiabusiness": "IN", "indianstartups": "IN", "india": "IN",
}


def detect_country(text: str, source_detail: str = "") -> tuple[str, str]:
    """(ISO-2 country, how we decided). '' if we genuinely cannot tell.

    Guessing is worse than not knowing: the country decides the currency you
    quote in, and quoting a UK shop in rupees ends the conversation.
    """
    low = text.lower()

    for pattern, country in _ENTITY_SUFFIX:
        if re.search(pattern, low):
            return country, "entity_suffix"

    for pattern, country in _CURRENCY_TAX:
        if re.search(pattern, low):
            return country, "currency_tax"

    sub = source_detail.lower()
    if sub in _SUB_COUNTRY:
        return _SUB_COUNTRY[sub], "subreddit"

    return "", ""


# --- extraction ---------------------------------------------------------------

def _clean_email(raw: str) -> str:
    email = raw.strip().lower().rstrip(".,;:)")
    local, _, domain = email.partition("@")
    if not domain or "." not in domain:
        return ""
    if local in JUNK_LOCALPARTS or domain in JUNK_DOMAINS:
        return ""
    if domain.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
        return ""
    return email


def extract(text: str, source_detail: str = "") -> dict[str, str]:
    """Everything we can honestly pull out of one post's text."""
    out = {"email": "", "phone": "", "website": "", "country": "",
           "geo_method": ""}

    for match in EMAIL_RE.findall(text or ""):
        email = _clean_email(match)
        if email:
            out["email"] = email
            break

    phone = PHONE_RE.search(text or "")
    if phone:
        digits = re.sub(r"\D", "", phone.group(0))
        # Below 10 digits it is not a phone number, it is a year or a price.
        if 10 <= len(digits) <= 15:
            out["phone"] = phone.group(0).strip()

    for url in URL_RE.findall(text or ""):
        host = url.split("//", 1)[-1].split("/", 1)[0].lower()
        if not any(social in host for social in SOCIAL_HOSTS):
            out["website"] = url.rstrip(").,")
            break

    country, method = detect_country(text or "", source_detail)
    out["country"] = country
    out["geo_method"] = method
    return out


# --- WhatsApp -----------------------------------------------------------------
#
# The user is in India and cannot dial a UK or US landline, so the phone column
# is only actionable as a WhatsApp link. wa.me wants bare E.164 digits: no "+",
# no spaces, no leading zeros.

_DIAL_CODES = {"GB": "44", "IN": "91", "US": "1", "CA": "1", "AU": "61",
               "DE": "49", "NL": "31", "FR": "33", "IE": "353", "NZ": "64"}


def to_e164(phone: str, country: str = "") -> str:
    """Bare E.164 digits ("441134960000"), or "" when we cannot be SURE.

    A wrong guess here WhatsApps a stranger, which is worse than an empty cell —
    so anything ambiguous returns "" rather than a maybe.
    """
    phone = (phone or "").strip()
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)

    if phone.startswith("+"):
        out = digits                       # already international (OSM's norm)
    elif digits.startswith("00") and len(digits) > 10:
        out = digits[2:]                   # 00 international-dial prefix
    else:
        code = _DIAL_CODES.get(country, "")
        if not code:
            return ""                      # national format, unknown country
        if digits.startswith("0"):
            out = code + digits[1:]        # 0113... -> 44113...
        elif country in {"US", "CA"} and len(digits) == 10:
            out = code + digits
        elif country not in {"US", "CA"} and len(digits) == 10:
            out = code + digits            # bare IN/AU-style mobile
        else:
            return ""
    return out if 8 <= len(out) <= 15 else ""


def wa_link(phone: str, country: str = "") -> str:
    """A click-to-chat link, or "" if the number cannot be normalised."""
    e164 = to_e164(phone, country)
    return f"https://wa.me/{e164}" if e164 else ""


def channel(platform: str, email: str, phone: str) -> str:
    """Where you would actually reach this person.

    This is the field that drives the drafting stage: a public_reply is a
    different genre of writing from an email, and using the wrong one is how you
    get banned rather than hired.
    """
    if platform == "jobboards":
        return "bid"
    if email:
        return "email"
    if phone:
        return "phone"
    if platform in {"reddit", "bluesky", "mastodon", "hackernews", "lobsters"}:
        return "public_reply"
    return "form"
