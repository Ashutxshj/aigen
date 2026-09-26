"""Central configuration: env loading + pipeline constants."""

import os

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


# --- Delivery (Resend — the lead REPORT to the operator, never to a prospect) ---
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

# --- Sourcing ---
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass/crawler-google-places")
APIFY_MAX_PLACES_PER_SEARCH = _env_int("APIFY_MAX_PLACES_PER_SEARCH", 20)
# Bound credit burn. This repo asks the actor for ALL places (see target_sourcer:
# `website: allPlaces`) rather than only website-less ones, so a given sweep
# returns more items than scraper2's would. Keep this cap tight.
APIFY_MAX_SEARCHES = _env_int("APIFY_MAX_SEARCHES", 12)

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
# Optional manual feed. Columns:
#   business_name,phone,rating,reviews,address,category,website,instagram
SEED_FILE = "seed_places.csv"

# The cities searched, as "{category} in {city}". Delhi NCR first — the home
# market, and the one you can meet in person — then the other metros, which are
# just as reachable for work delivered remotely anyway.
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

# Target customer profile: SMALL BUSINESS OWNERS who live on Instagram and have
# no real website — people for whom content is a chore that steals time from the
# actual money-maker, not content-native pros. Deliberately NO healthcare (a
# surgeon does not read DMs) and NO beauty vertical (salons, nail studios,
# makeup artists are already extremely content-efficient on Instagram — they are
# the one local segment that does not need help posting; see BEAUTY_KEYWORDS).
#
# WARNING before adding a category: EXCLUDED_KEYWORDS below is substring-matched
# against the business name AND the Maps category label. Any category containing
# "digital", "tech", "website", "social media", "marketing", "branding", "seo",
# "web design" or "graphic design" silently self-filters and returns nothing.
# "photographer" and "interior designer" are safe — the blocklist holds
# "graphic design"/"web design", not bare "design".
BUSINESS_CATEGORIES = [
    "cafe",
    "restaurant",
    "bakery",
    "sweet shop",
    "cloud kitchen",
    "gym",
    "fitness studio",
    "yoga studio",
    "dance studio",
    "photographer",
    "home decor store",
    "furniture store",
    "pet grooming",
    "pet shop",
    "event planner",
    "wedding planner",
    "caterer",
    "interior designer",
    "coaching institute",
    "preschool",
]

# The whole beauty/fashion/girly cluster is dropped, even when a sweep returns
# it under another query (a "cafe" search often surfaces the boutique next
# door): salons/nails/spa/makeup AND boutiques, jewellers, fashion/apparel,
# florists, gifts, bridal/mehndi. These verticals are already content-native on
# Instagram — not prospects for content or website help. Matched as WHOLE WORDS
# against name + Maps category — substring matching would kill "Spanish Tapas"
# on "spa" or "Sparsh" on "spa".
BEAUTY_FASHION_KEYWORDS = [
    # beauty
    "salon", "salons", "spa", "spas", "nail", "nails", "makeup", "mua",
    "beauty", "parlour", "parlor", "hairdresser", "barber", "cosmetics",
    "cosmetic", "skincare",
    # fashion / girly
    "boutique", "boutiques", "jewellery", "jewelry", "jeweller", "jewellers",
    "jeweler", "jewelers", "fashion", "apparel", "clothing", "garment",
    "garments", "saree", "sarees", "lehenga", "bridal", "mehndi", "mehendi",
    "florist", "florists", "flower", "flowers", "gift", "gifts", "handbag",
    "handbags", "accessories",
]

# Businesses that SELL tech / digital-marketing services — peers, not prospects.
# Matched case-insensitively against business name + the Maps category label.
EXCLUDED_KEYWORDS = [
    "digital", "marketing", "seo", "branding", "advertis", "adagenc",
    "ad agenc", "media house",
    "social media", "software", "tech", "infotech", "it solution", "it service",
    "saas", "web design", "webdesign", "web develop", "webdev", "website",
    "app develop", "graphic design",
]

# The NCR-only gate is GONE on purpose: DM outreach is delivered remotely, so a
# boutique in Pune is exactly as workable as one in Noida. Searches stay
# country-locked to India via the Apify countryCode.

# --- DM sheet mode (main.py --dm-out) ---
# Scan up to DM_POOL Instagram-reachable candidates, return the best DM_TOP as
# a sheet of clickable profile + DM links.
DM_POOL = _env_int("DM_POOL", 30)
DM_TOP = _env_int("DM_TOP", 10)

# One batched Apify call per DM run checks each candidate's profile: private
# and non-existent accounts are dropped, and so is anyone posting at or above
# this rate — a business already shipping reels near-daily has content handled
# and will never buy content help (see ig_activity.py).
IG_PROFILE_ACTOR_ID = os.getenv("IG_PROFILE_ACTOR_ID",
                                "apify/instagram-profile-scraper")
ACTIVE_POSTS_PER_WEEK = _env_float("ACTIVE_POSTS_PER_WEEK", 4.0)

# --- Web presence (see web_presence.py) ---
# Reported per-lead in its own column. Kept OFF the Lead Type axis on purpose:
# `stats` is seeded with exactly the two tier keys below, so a third tier string
# would KeyError on `stats[lead_type] += 1`.
PRESENCE_INSTAGRAM = "Instagram DM"
PRESENCE_FACEBOOK = "Facebook page"
PRESENCE_PHONE_ONLY = "Phone only"

# --- Lead tiers (quality axis only — never reachability) ---
LEAD_TYPE_GOLDENROD = "Goldenrod"
LEAD_TYPE_NEW_BARK = "New Bark"
GOLDENROD_MIN_RATING = _env_float("GOLDENROD_MIN_RATING", 4.5)
GOLDENROD_MIN_REVIEWS = _env_int("GOLDENROD_MIN_REVIEWS", 500)
GOLDENROD_FILL_HEX = "FFDF00"

MAX_TARGETS = _env_int("MAX_TARGETS", 0)  # 0 = unlimited
REQUEST_TIMEOUT = 15
REQUEST_DELAY_SECONDS = _env_float("REQUEST_DELAY_SECONDS", 1.0)

# --- Anti-ban: retry/backoff + jitter ---
MAX_RETRIES = _env_int("MAX_RETRIES", 3)
BACKOFF_BASE_SECONDS = _env_float("BACKOFF_BASE_SECONDS", 1.5)
BACKOFF_MAX_SECONDS = _env_float("BACKOFF_MAX_SECONDS", 30.0)
JITTER_MIN_SECONDS = _env_float("JITTER_MIN_SECONDS", 0.8)
JITTER_MAX_SECONDS = _env_float("JITTER_MAX_SECONDS", 2.5)

# --- Anti-ban: rotating proxies ---
PROXY_LIST = os.getenv("PROXY_LIST", "")
PROXY_FILE = os.getenv("PROXY_FILE", "proxies.txt")
PROXY_MAX_FAILURES = _env_int("PROXY_MAX_FAILURES", 3)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# --- Output ---
# Leads go straight into the ONE master workbook, Projects/leads_master.xlsx
# (see master_registry.py). No output/ folder, no per-run CSV or XLSX, no
# per-repo registry. Dedup lives in the master file.
SENDS_LOG_FILE = "sends_log.jsonl"
