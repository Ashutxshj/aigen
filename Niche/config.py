"""Niche configuration: env loading, the niche dropdown list, cities, and keys.

Secrets are NOT stored in this repo by default. The loader reads Niche/.env
first (for overrides), then falls back to scraper2/.env — which already holds
the working APIFY_TOKEN and RESEND_API_KEY — so the tool runs out of the box
without a single key being copied anywhere new.

The launcher imports this file (via importlib) only to read NICHES for its
dropdown, so importing must stay side-effect-free beyond os.environ.setdefault.
"""

import os
import re

NICHE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(NICHE_DIR)                     # ...\Projects
OUT_DIR = os.path.join(NICHE_DIR, "out")
SEEN_FILE = os.path.join(NICHE_DIR, "seen.json")


# --- .env (tiny loader, no dependency; same as launcher's) -------------------

def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            # scraper2's .env carries trailing "  # comment"s on some values.
            value = re.split(r"\s+#", value, 1)[0]
            os.environ.setdefault(key.strip(), value.strip())


# Niche's own .env wins; launcher's then scraper2's .env supply whatever is
# missing (setdefault semantics — an already-set variable is never overwritten).
# launcher/.env goes before scraper2/.env so the recipient matches the inbox
# every other launcher button already mails (LAUNCHER_RECIPIENT).
_load_dotenv(os.path.join(NICHE_DIR, ".env"))
_load_dotenv(os.path.join(ROOT, "launcher", ".env"))
_load_dotenv(os.path.join(ROOT, "data-analysis2", ".env"))  # scraper2, renamed on disk

# --- delivery (Resend) -------------------------------------------------------

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM_EMAIL",
                        os.getenv("RESEND_FROM", "onboarding@resend.dev")).strip()
RECIPIENT = os.getenv("NICHE_RECIPIENT",
                      os.getenv("RECIPIENT_EMAIL", "ashutosh06066@gmail.com")).strip()

# --- sourcing (Apify preferred, Google Places fallback) ----------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass/crawler-google-places")
APIFY_MAX_PLACES_PER_SEARCH = _env_int("APIFY_MAX_PLACES_PER_SEARCH", 20)
APIFY_MAX_SEARCHES = _env_int("APIFY_MAX_SEARCHES", 8)
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

# The cities a niche is swept across, as "{niche} in {city}". NCR first (the
# home market), then the other metros. The Apify cost knob is APIFY_MAX_SEARCHES:
# queries are cut off at that count, so the first cities in this list are the
# ones a small cap is spent on.
TARGET_CITIES = [
    "Delhi",
    "New Delhi",
    "Noida",
    "Greater Noida",
    "Gurgaon",
    "Faridabad",
    "Ghaziabad",
    "Mumbai",
    "Bengaluru",
    "Hyderabad",
    "Chennai",
    "Pune",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
]

# --- the dropdown ------------------------------------------------------------
# Every niche the launcher UI offers. Each is a Google Maps search term, so it
# must read naturally as "{niche} in Delhi".
NICHES = [
    "restaurants",
    "cafes",
    "bakeries",
    "cloud kitchens",
    "sweet shops",
    "dentists",
    "doctors",
    "medical clinics",
    "physiotherapists",
    "diagnostic labs",
    "salons",
    "spas",
    "gyms",
    "yoga studios",
    "boutiques",
    "jewellers",
    "furniture stores",
    "electronics shops",
    "mobile repair shops",
    "opticians",
    "pet shops",
    "florists",
    "gift shops",
    "toy stores",
    "book stores",
    "coaching institutes",
    "tutors",
    "play schools",
    "dance academies",
    "music classes",
    "photographers",
    "event planners",
    "wedding planners",
    "caterers",
    "interior designers",
    "architects",
    "real estate agents",
    "travel agencies",
    "car repair garages",
    "car washes",
    "bike showrooms",
    "tailors",
    "dry cleaners",
    "packers and movers",
    "printing shops",
    "hardware stores",
    "chartered accountants",
    "lawyers",
    "insurance agents",
    "banquet halls",
]

# Businesses that SELL digital services — peers, not prospects. Matched
# case-insensitively against name + category; any hit skips the target.
EXCLUDED_KEYWORDS = [
    "digital", "marketing", "seo", "branding", "advertis", "ad agenc",
    "social media", "software", "tech", "infotech", "it solution", "it service",
    "saas", "web design", "webdesign", "web develop", "webdev", "website",
    "app develop", "graphic design",
]

MAX_TARGETS = _env_int("MAX_TARGETS", 0)              # 0 = unlimited
REQUEST_TIMEOUT = 15
