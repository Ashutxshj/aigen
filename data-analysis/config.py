"""Central configuration: env loading + pipeline constants."""

import os
import re

from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")

# --- Delivery (Resend, per wa1.txt report-generator theory) ---
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "ashutosh06066@gmail.com")

# --- Sourcing ---
# Apify Google Maps Scraper (card-free, preferred). Presence of the token
# activates Apify mode ahead of Google Places.
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass/crawler-google-places")
APIFY_MAX_PLACES_PER_SEARCH = _env_int("APIFY_MAX_PLACES_PER_SEARCH", 20)
APIFY_MAX_SEARCHES = _env_int("APIFY_MAX_SEARCHES", 20)  # bound credit burn

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
SEED_FILE = "seed_urls.csv"

# The cities searched, as "{category} in {city}". Delhi NCR first — it is the
# home market and the one you can meet in person — then the other metros, which
# are just as reachable for work that is delivered remotely anyway.
#
# COST: queries = categories x cities, capped by APIFY_MAX_SEARCHES. Adding a
# city does NOT by itself cost more; it changes what the cap is spent on. The
# query list is category-major (see target_sourcer._search_queries), so the cap
# spreads across every city rather than being exhausted on Delhi. Raise
# APIFY_MAX_SEARCHES to cover more categories per city — that is the knob that
# costs money, and it scales linearly.
TARGET_CITIES = [
    # Delhi NCR
    "Delhi",
    "New Delhi",
    "Noida",
    "Greater Noida",
    "Gurgaon",
    "Faridabad",
    "Ghaziabad",
    # The other metros
    "Mumbai",
    "Bengaluru",
    "Hyderabad",
    "Chennai",
    "Pune",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
]

# Target customer profile: local businesses/orgs that BUY web & digital services.
# Sellers of those services (tech / digital-marketing) are excluded — see
# EXCLUDED_KEYWORDS below.
BUSINESS_CATEGORIES = [
    "dentist",
    "medical clinic",
    "restaurant",
    "cafe",
    "salon",
    "gym",
    "law firm",
    "real estate agency",
    "coaching institute",
    "consultant",
    "chartered accountant",
    "boutique shop",
    "manufacturing company",
    "NGO",
]

# CSV "Category" buckets — first keyword hit (against the Maps category label +
# business name + picked menu category) wins, so order specific before generic.
CATEGORY_BUCKETS = [
    ("Doctors", ["dentist", "dental", "clinic", "doctor", "medical", "hospital",
                 "physician", "healthcare", "homeopath", "ayurved", "diagnostic"]),
    ("Restaurants & Cafes", ["restaurant", "cafe", "coffee", "bakery", "dining",
                             "food", "kitchen", "bar "]),
    ("Salons & Beauty", ["salon", "spa", "beauty", "parlour", "parlor", "makeup"]),
    ("Gyms & Fitness", ["gym", "fitness", "yoga", "crossfit"]),
    ("Legal", ["law firm", "lawyer", "advocate", "attorney", "legal", "law"]),
    ("Finance & Accounting", ["chartered accountant", "accountant", "accounting",
                              "tax", "audit"]),
    ("Real Estate", ["real estate", "property", "builder", "realtor"]),
    ("Education & Coaching", ["coaching", "institute", "academy", "school",
                              "tuition", "education", "training"]),
    ("Consultants", ["consultant", "consultancy", "consulting"]),
    ("Retail Shops", ["boutique", "shop", "store", "retail"]),
    ("Manufacturing", ["manufactur", "factory", "industries", "industrial"]),
    ("NGOs", ["ngo", "foundation", "charitable", "charity", "welfare", "trust"]),
]

# Aggregators / directories / socials — never the business's own domain.
AGGREGATOR_DOMAINS = {
    "justdial.com", "indiamart.com", "sulekha.com", "yelp.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "google.com", "goo.gl", "wa.me", "whatsapp.com",
    "tradeindia.com", "exportersindia.com", "zomato.com", "swiggy.com",
    "magicbricks.com", "99acres.com", "housing.com", "urbancompany.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "business.site",
}

# Businesses that SELL tech / digital-marketing services — peers, not prospects.
# Matched case-insensitively against business name + registrable domain + the
# Maps category label; any hit skips the target before WHOIS/scraping spend.
EXCLUDED_KEYWORDS = [
    "digital", "marketing", "seo", "branding", "advertis", "adagenc",
    "ad agenc", "media house",
    "social media", "software", "tech", "infotech", "it solution", "it service",
    "saas", "web design", "webdesign", "web develop", "webdev", "website",
    "app develop", "graphic design",
]

# Accepted place locations — lowercase substring match against the city/address
# Apify returns.
NCR_CITY_KEYWORDS = [
    "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad",
]
# Enforce the NCR gate? OFF by default, and it must stay off while TARGET_CITIES
# reaches beyond the NCR: this gate drops anything whose address names no NCR
# city, so with it on, every Mumbai and Chennai place we just paid Apify to find
# would be thrown straight back. Apify is already country-locked to India
# (countryCode=in), which is the only geography check that still matters.
# Set NCR_ONLY=true to go back to Delhi NCR alone.
NCR_ONLY = _env_bool("NCR_ONLY", False)

# --- Sitemap staleness filter (sitemap.xml <lastmod>) ---
# STALE-ONLY: keep a site only if last updated >= MIN_STALE_DAYS ago — a
# neglected site is the redesign lead. Recently-updated sites are discarded.
MIN_STALE_DAYS = 365
SITEMAP_MAX_CHILDREN = _env_int("SITEMAP_MAX_CHILDREN", 3)  # index children fetched
# Brand-new-domain window — used ONLY by the opt-in --fresh sweep (fresh_domains.py).
MAX_FRESH_DAYS = 7

# --- Fresh-domain sweep (opt-in via --fresh) ---
# Newly-registered-domain lists are pulled for this many past days (capped at
# MAX_FRESH_DAYS so everything sourced is inside the "brand new" window).
FRESH_NRD_DAYS_BACK = _env_int("FRESH_NRD_DAYS_BACK", 7)
FRESH_MAX_DOMAINS = _env_int("FRESH_MAX_DOMAINS", 25)  # live sites kept per run
# A new registration is an NCR candidate if its name contains one of these.
# (Deliberately no bare "ncr" — it substring-matches words like "concrete".)
FRESH_DOMAIN_KEYWORDS = [
    "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad",
]

# --- Contact scraper ---
CONTACT_PATHS = ["", "/contact", "/contact-us", "/contactus", "/about", "/about-us", "/reach-us"]
MAX_PAGES_PER_SITE = 4
REQUEST_TIMEOUT = 15
REQUEST_DELAY_SECONDS = _env_float("REQUEST_DELAY_SECONDS", 1.0)
USE_PLAYWRIGHT = os.getenv("USE_PLAYWRIGHT", "0") == "1"
MAX_TARGETS = _env_int("MAX_TARGETS", 0)  # 0 = unlimited

# --- Anti-ban: retry/backoff + jitter (applies to all HTTP fetches) ---
MAX_RETRIES = _env_int("MAX_RETRIES", 3)          # attempts per request on 429/503/timeout
BACKOFF_BASE_SECONDS = _env_float("BACKOFF_BASE_SECONDS", 1.5)  # exponential base
BACKOFF_MAX_SECONDS = _env_float("BACKOFF_MAX_SECONDS", 30.0)   # cap per wait
# Randomized inter-request delay window (overrides the fixed delay when max > 0).
JITTER_MIN_SECONDS = _env_float("JITTER_MIN_SECONDS", 0.8)
JITTER_MAX_SECONDS = _env_float("JITTER_MAX_SECONDS", 2.5)

# --- Anti-ban: rotating proxies ---
# Comma-separated in PROXY_LIST, and/or one-per-line in proxies.txt.
# Each entry: scheme://[user:pass@]host:port  (http/https/socks5).
PROXY_LIST = os.getenv("PROXY_LIST", "")
PROXY_FILE = os.getenv("PROXY_FILE", "proxies.txt")
PROXY_MAX_FAILURES = _env_int("PROXY_MAX_FAILURES", 3)  # strikes before a proxy is dropped

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
OBFUSCATED_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s@\s|\bat\b)\s*"
    r"([A-Za-z0-9\-]+)\s*(?:\[dot\]|\(dot\)|\bdot\b)\s*([A-Za-z]{2,})",
    re.IGNORECASE,
)

# Junk email fragments (asset names, platform internals, placeholders).
EMAIL_JUNK_PATTERNS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    "example.com", "email.com", "domain.com", "yourdomain", "sentry",
    "wixpress", "@2x", "no-reply@", "noreply@",
)

# Indian phone formats:
#   +91 / 0091 / 91 prefixed 10-digit mobiles (6-9 start), with separators;
#   bare 10-digit mobiles; NCR landlines 011/0120/0124/0129/0130/0131 + 6-8 digits.
PHONE_RE = re.compile(
    r"(?:(?:\+|00)?91[\s\-.]?)?"          # optional country code
    r"(?:\(?0?\)?[\s\-.]?)?"              # optional leading 0
    r"([6-9]\d{4}[\s\-.]?\d{5})"          # 10-digit mobile (split allowed)
    r"|"
    r"(0(?:11|12[0-9]|13[0-1])[\s\-.]?\d{6,8})"  # NCR landline
)

# --- Output ---
# Leads go straight into the ONE master workbook, Projects/leads_master.xlsx
# (see master_registry.py). No output/ folder, no per-run CSV. The site audit
# still runs — its findings become the master's bullet-points column.
SENDS_LOG_FILE = "sends_log.jsonl"
