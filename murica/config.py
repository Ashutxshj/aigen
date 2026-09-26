"""Murica configuration: env loading, the 50-state dropdown, categories, keys.

Secrets are NOT stored in this repo by default. The loader reads murica/.env
first (for overrides), then launcher/.env, then scraper2/.env — which already
holds the working APIFY_TOKEN and RESEND_API_KEY — so the tool runs out of the
box without a single key being copied anywhere new.

The launcher reads STATES out of this file (via ast, not import) for its
dropdown, so STATES must stay a plain list literal.

Cost note: the Apify knobs use MURICA_* names on purpose, so scraper2's much
bigger APIFY_MAX_SEARCHES never leaks in through the .env fallback chain. One
run costs min(len(CATEGORIES-slice), MURICA_MAX_SEARCHES) x
MURICA_PLACES_PER_SEARCH crawled places; the WHOIS checks after that are free.
"""

import os
import re

MURICA_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(MURICA_DIR)                    # ...\Projects
OUT_DIR = os.path.join(MURICA_DIR, "out")
SEEN_FILE = os.path.join(MURICA_DIR, "seen.json")
AGE_CACHE_FILE = os.path.join(MURICA_DIR, "age_cache.json")
PROGRESS_FILE = os.path.join(MURICA_DIR, "progress.json")
FAMOUS_FILE = os.path.join(MURICA_DIR, "famous_brands.csv")


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


# murica's own .env wins; launcher's then scraper2's .env supply whatever is
# missing (setdefault semantics — an already-set variable is never overwritten).
_load_dotenv(os.path.join(MURICA_DIR, ".env"))
_load_dotenv(os.path.join(ROOT, "launcher", ".env"))
_load_dotenv(os.path.join(ROOT, "data-analysis2", ".env"))  # scraper2, renamed on disk

# --- delivery (Resend) -------------------------------------------------------

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM_EMAIL",
                        os.getenv("RESEND_FROM", "onboarding@resend.dev")).strip()
RECIPIENT = os.getenv("MURICA_RECIPIENT",
                      os.getenv("LAUNCHER_RECIPIENT", "ashutosh06066@gmail.com")).strip()

# --- sourcing (Apify Google Maps) --------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass/crawler-google-places")
# MURICA_* on purpose — see the module docstring.
APIFY_MAX_SEARCHES = _env_int("MURICA_MAX_SEARCHES", 6)
APIFY_MAX_PLACES_PER_SEARCH = _env_int("MURICA_PLACES_PER_SEARCH", 25)

# --- the lead definition -----------------------------------------------------

# A lead is valid when its own domain was registered at least this long ago.
MIN_AGE_YEARS = _env_int("MURICA_MIN_AGE_YEARS", 10)
# Every run stops once this many valid leads are found (the whole point:
# 10 fresh leads per click, no more Apify spend than that needs).
RESULTS_PER_RUN = _env_int("MURICA_RESULTS_PER_RUN", 10)

# --- the dropdown ------------------------------------------------------------
# All 50 US states. Each is used verbatim in the Maps query
# "{category} in {state}, USA" and as the state key in progress.json.
STATES = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
]

# The business categories a state is swept across, as "{category} in {state}".
# All are SMB types that went online in the 2000s and rarely rebuilt — exactly
# where decade-old websites live. Each run takes the NEXT slice of this list
# for the chosen state (progress.json remembers the offset), so repeat runs on
# one state keep finding new ground instead of re-billing the same searches.
CATEGORIES = [
    "law firms",
    "dentists",
    "accounting firms",
    "auto repair shops",
    "plumbers",
    "hvac contractors",
    "roofing contractors",
    "insurance agencies",
    "real estate agencies",
    "funeral homes",
    "veterinarians",
    "chiropractors",
    "family restaurants",
    "electricians",
    "towing companies",
    "printing shops",
    "dry cleaners",
    "pest control services",
    "moving companies",
    "landscaping companies",
    "medical clinics",
    "optometrists",
    "travel agencies",
    "furniture stores",
]

# Businesses that almost certainly ALREADY have a good website (they sell
# looks or tech for a living) plus digital-service peers. Matched
# case-insensitively against name + category; any hit skips the target.
# Same idea as Niche's EXCLUDED_KEYWORDS and scraper3's beauty-cluster drop.
EXCLUDED_KEYWORDS = [
    # sells digital/marketing services — a peer, not a prospect
    "digital", "marketing", "seo", "branding", "advertis", "ad agenc",
    "social media", "software", "tech", "infotech", "it solution",
    "it service", "saas", "web design", "webdesign", "web develop", "webdev",
    "website", "app develop", "graphic design", "media agenc",
    "creative agenc",
    # beauty/fashion — image-native, their sites are already polished
    "salon", "spa", "nail", "lash", "brow", "makeup", "beauty", "barber",
    "boutique", "fashion", "jewel", "bridal", "wedding", "tattoo",
    "aesthetic", "cosmetic", "skincare", "hair",
    # design-native trades — a dated portfolio site would kill their business
    "photograph", "videograph", "interior design", "architect",
]

# The "website" Google Maps shows is often just a profile on a platform. A
# platform domain's WHOIS date is the PLATFORM's birthday, not the business's,
# so any of these as the registrable domain disqualifies the target outright
# (they also aren't "owns an old website" businesses in the first place).
PLATFORM_DOMAINS = {
    "facebook.com", "instagram.com", "linktr.ee", "business.site",
    "google.com", "wixsite.com", "wix.com", "squarespace.com",
    "wordpress.com", "blogspot.com", "weebly.com", "webs.com",
    "godaddysites.com", "square.site", "myshopify.com", "shopify.com",
    "yelp.com", "tripadvisor.com", "yellowpages.com", "mapquest.com",
    "angi.com", "houzz.com", "thumbtack.com", "homeadvisor.com",
    "doordash.com", "ubereats.com", "grubhub.com", "toasttab.com",
    "zocdoc.com", "healthgrades.com", "avvo.com", "lawyers.com",
    "zillow.com", "realtor.com", "homes.com",
}

MAX_TARGETS = _env_int("MAX_TARGETS", 0)              # 0 = unlimited candidates
REQUEST_TIMEOUT = 15
WHOIS_DELAY_SECONDS = 0.5     # politeness gap between RDAP/WHOIS lookups
