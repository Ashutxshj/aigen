"""Every knob in one place: env loading, paths, per-platform rate budgets.

This tool NEVER sends anything. There is no SMTP client, no Reddit DM call and
no --send flag anywhere in this repo. It drafts a suggested PUBLIC COMMENT and a
human decides whether to post it.

It also never touches Projects/leads_master.xlsx. That workbook belongs to the
other repos. Output goes to its own file (INTENT_FILE, default
Projects/intent_leads.xlsx) and its own SQLite working store (leeds/leads.db).
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.dirname(BASE_DIR)


def _load_dotenv() -> None:
    """Read BASE_DIR/.env into the environment. Real env vars win.

    Hand-rolled so python-dotenv is not a dependency (same trick as
    email-automation/config.py).
    """
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# --- Paths -------------------------------------------------------------------

# The ONLY workbook this repo writes. Deliberately NOT leads_master.xlsx.
INTENT_FILE = os.getenv(
    "INTENT_FILE", os.path.join(PROJECTS_DIR, "intent_leads.xlsx"))
DB_PATH = os.getenv("LEEDS_DB", os.path.join(BASE_DIR, "leads.db"))
FIXTURES_DIR = os.path.join(BASE_DIR, "fixtures")

# --- Window ------------------------------------------------------------------

# Recency is a HARD GATE, not a score input. Anything older is dropped outright.
DEFAULT_SINCE_HOURS = 48

# --- Time --------------------------------------------------------------------
#
# EVERYTHING is stored, compared and windowed in UTC. That is not negotiable: the
# sources publish UTC, the 48h cut is global, and a naive local timestamp shifts
# the window by your offset — at +05:30 that drops half a day of live leads and
# keeps half a day of dead ones.
#
# But YOU read the spreadsheet, and you are in India. So the workbook — and ONLY
# the workbook — renders in local time. Storage stays UTC; the conversion happens
# at the last possible moment, in export/excel.py.
#
# A fixed offset rather than zoneinfo, deliberately: India has no DST, so +05:30
# is exactly right all year and it needs no tzdata package on Windows.
DISPLAY_TZ_NAME = os.getenv("DISPLAY_TZ_NAME", "IST")
DISPLAY_UTC_OFFSET_MINUTES = int(os.getenv("DISPLAY_UTC_OFFSET_MINUTES", "330"))

# --- HTTP --------------------------------------------------------------------

REQUEST_TIMEOUT = 25
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0

# Scrape-path jitter only. API calls are NOT jittered: on an authenticated API
# you are already identified by client id, so jitter buys nothing and just makes
# the run slower.
JITTER_MIN_SECONDS = 0.4
JITTER_MAX_SECONDS = 1.2

PROXY_LIST = os.getenv("PROXY_LIST", "")
PROXY_FILE = os.getenv("PROXY_FILE", "")
PROXY_MAX_FAILURES = 3

CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "ashutosh06066@gmail.com")

# Descriptive bot UA for official APIs. A generic python-requests UA gets
# throttled; a fake Chrome UA on an API is a terms violation.
API_USER_AGENT = os.getenv(
    "API_USER_AGENT", f"chillispark-leeds/0.1.0 (+{CONTACT_EMAIL})")

# Reddit MANDATES this shape: platform:app_id:version (by /u/username).
# https://github.com/reddit-archive/reddit/wiki/API
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT",
    "python:com.chillispark.leeds:v0.1.0 (by /u/your_reddit_handle)")

# Browser-shaped UAs are used ONLY when probing a small business's own website
# or an HTML directory page — never against an API.
BROWSER_USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
     "Gecko/20100101 Firefox/126.0"),
]

# --- Rate limits -------------------------------------------------------------
#
# Bucket spec: (capacity, refill_per_second, daily_quota|None).
# Token bucket persisted in SQLite so the budget holds ACROSS RUNS — a bucket
# that resets per process blows the limit the moment the user runs twice in five
# minutes. The bucket KEY is declared by each collector (see Collector.bucket),
# not derived from the hostname: Reddit's limit is per OAuth client id, and
# Mastodon's is per (account, instance) so each instance gets its own bucket.
#
# Sources:
#   reddit        100 QPM per OAuth client id, averaged over 10 minutes. We run
#                 at 60/min and additionally obey the X-Ratelimit-* response
#                 headers (see core/api_http.py) rather than trusting this table.
#                 https://support.reddithelp.com/hc/en-us/articles/16160319875092
#   hackernews    Algolia: no hard published cap (~10k/h); Firebase: none. 30/min
#                 is a self-imposed courtesy limit.  https://hn.algolia.com/api
#   stackexchange a DAILY QUOTA, not a rate: 300/day anonymous, 10,000/day with a
#                 free key. Plus a mandatory `backoff` field in the response body
#                 which we honour.  https://api.stackexchange.com/docs/throttle
#   bluesky       3000 req / 5 min per IP on the appview.
#                 https://docs.bsky.app/docs/advanced-guides/rate-limits
#   mastodon      300 req / 5 min per account+IP. One bucket PER INSTANCE.
#   overpass      ~2 concurrent slots per IP; be gentle: 1 query / 10 s.
#   places        opt-in only (billing card required since Mar 2025).
#   jobboards     1 request / 3 s per host.
#   wordpress     wordpress.org support forums: no published cap; 15/min courtesy.
#   registries    Companies House: 600 req / 5 min with a free key.
#   newdomains    WhoisDS regenerates once a day; 1/day is all that's useful.
RATE_LIMITS: dict[str, tuple[float, float, int | None]] = {
    "reddit":        (10, 60 / 60.0, None),
    "hackernews":    (5, 30 / 60.0, None),
    "stackexchange": (3, 20 / 60.0, 300),      # daily quota; 10k if a key is set
    "bluesky":       (10, 60 / 60.0, None),
    "mastodon":      (5, 60 / 300.0, None),    # per instance, see bucket key
    "feeds":         (2, 1 / 3.0, None),
    "jobboards":     (1, 1 / 3.0, None),
    "wordpress":     (3, 15 / 60.0, None),
    "overpass":      (1, 1 / 10.0, None),
    "places":        (5, 1.0, None),
    "justdial":      (1, 1 / 10.0, None),
    # Capacity 2, not 1: the collector legitimately fetches NRD_DAYS_BACK feeds
    # in one run, and a capacity-1 bucket refilling once a day made the SECOND
    # fetch wait 24h. The "2 a day" budget is enforced by the daily quota, which
    # is the right mechanism for it.
    "newdomains":    (2, 1 / 86400.0, 2),
    "registries":    (10, 600 / 300.0, None),
    "web":           (2, 1 / 2.0, None),       # generic site probes
    "dns":           (5, 5.0, None),
    # Arctic Shift is a free, community-run archive. It has no published limit,
    # and it does NOT answer 429 when you push it — it answers
    #     HTTP 422  {"error": "Timeout. Maybe slow down a bit"}
    # which any normal client treats as a permanent client error and gives up on.
    # Measured: 1 request every ~3s is comfortable; 1 every 1.5s got 422s.
    "arcticshift":   (1, 1 / 3.0, None),
    # Google CSE free tier is a HARD 100/day. The daily quota is the real limit,
    # not the rate — so it is expressed as a quota and acquire() SKIPS rather
    # than sleeping when it is gone (it will not refill for hours).
    "websearch":     (5, 1.0, 95),             # 95, not 100: leave headroom
}
STACKEXCHANGE_QUOTA_WITH_KEY = 10_000

# --- Reddit ------------------------------------------------------------------

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "").strip()

# Reddit WITHOUT an account. Set this and the OAuth collector is never used, so
# no app, no client id, and your one remaining account is never touched.
#
# Reddit's own unauthenticated endpoints are dead — www.reddit.com/r/x/new.json
# and old.reddit.com both return 403 Blocked (verified 2026-07-11). Arctic Shift
# is the public archive that replaced Pushshift, and it serves posts AND comments
# with no auth. Measured lag on 2026-07-11: newest comment 0.0h, newest post
# 0.1-4.7h — effectively live, and fine for a 48h window.
USE_REDDIT_PUBLIC = os.getenv("USE_REDDIT_PUBLIC", "1") not in ("0", "false", "")

# DEMAND-SIDE subs only: places where people who BUY websites/SEO hang out.
#
# TIER A — the actually-unfished ones. Sampled from the Reddit archive: genuine
# owner demand threads here draw ~ZERO agency replies, while OFFER posts get
# removed by mods at 42-69%. The demand side is empty and the supply side is a
# graveyard. That asymmetry is the whole edge.
#   r/Chiropractic  "website hosts"            17 comments,  0 pitches
#   r/Dentistry     "Trying to build a Website" 21 comments, 0 pitches
#   r/Contractor    "Best website platform?"    26 comments, 0 pitches
#   r/Handyman      "lost an $8k job because I don't have a website"  584 comments
# These are also the highest-ticket buyers on the list — a dentist is not
# haggling over £400.
SUBS_TIER_A = [
    "Chiropractic", "Dentistry", "Contractor", "Handyman", "sweatystartup",
    "pressurewashing", "hvacadvice",   # NOT r/HVAC — that sub is for technicians
]

# TIER B — real demand, but agencies are present and/or mods are hostile.
SUBS_WEB_DESIGN = SUBS_TIER_A + [
    "smallbusiness", "AskSmallBusiness", "smallbusinessUK", "Entrepreneur",
    "EntrepreneurRideAlong", "startups", "Business_Ideas", "SideProject",
    "ecommerce", "Etsy", "EtsySellers", "ShopifyeCommerce", "restaurateur",
    "BarOwners", "realtors", "Roofing", "Plumbing", "electricians",
    "personaltraining", "Bookkeeping", "photography", "nocode",
    "squarespace", "wix", "GoDaddy",
    # DROPPED after sampling: r/lawncare (mostly homeowners, not owners),
    # r/Construction (saturated with "I'll build your website" spam),
    # r/KitchenConfidential (kitchen STAFF, not owners).
]
SUBS_SEO = [
    "SEO", "bigseo", "juststart", "AskMarketing", "marketing",
    "GoogleMyBusiness", "localseo",
]

# SUPPLY-SIDE subs. Every post here is a competitor, not a lead. r/web_design is
# ~95% designers; r/forhire is people advertising THEMSELVES for hire (the
# original brief listed it — it is exactly backwards). Never poll these, and if
# a crosspost surfaces from one, drop it.
ANTI_SUBREDDITS = {
    "forhire", "webdev", "web_design", "Frontend", "frontend", "reactjs",
    "javascript", "css", "html", "PHP", "laravel", "django", "programming",
    "learnprogramming", "webdesign", "slavelabour", "DoneDirtCheap",
}

# Per-sub multipliers on the rule score. r/Wordpress is half developers;
# r/freelance is mostly freelancers talking to each other.
SUBREDDIT_PRIORS: dict[str, float] = {
    "smallbusiness": 1.2,
    "AskSmallBusiness": 1.2,
    "Entrepreneur": 1.1,
    "EntrepreneurRideAlong": 1.1,
    "restaurateur": 1.15,
    "GoogleMyBusiness": 1.15,
    "Wordpress": 0.6,
    "wordpress": 0.6,
    "freelance": 0.5,
    "SEO": 0.8,          # agencies pitching outnumber buyers
    "bigseo": 0.7,
    "marketing": 0.9,
}

# /new + /comments is the SPINE: roughly a third of "I need a website" intent
# shows up as a COMMENT in a weekly megathread and never as its own post.
# /search is a supplement only — its index lags and recall is unreliable.
REDDIT_SEARCH_QUERIES = [
    "need a website", "looking for a web designer", "hire a web developer",
    "website for my business", "need help with SEO", "hire an SEO",
    "not showing up on google",
]
REDDIT_LISTING_LIMIT = 100     # the max Reddit allows per listing page

# --- Hacker News -------------------------------------------------------------

HN_QUERIES = [
    "need a website", "looking for a web designer", "hire seo", "seo help",
    "freelance web design",
]
# The monthly "Ask HN: Freelancer? Seeking freelancer?" thread (1st of the
# month). The SEEKING FREELANCER half is businesses stating what they need WITH
# an email address — by far the highest contact-density free source for this ICP.
HN_FREELANCER_QUERY = "Freelancer? Seeking freelancer?"
HN_FIREBASE = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
HN_MAX_THREAD_ITEMS = 400      # cap the comment-tree walk

# --- Feeds (declarative) -----------------------------------------------------
#
# Craigslist is DELIBERATELY ABSENT. Its robots.txt disallows /search, and the
# RSS feeds are served from /search?format=rss — so "collect Craigslist" and
# "obey robots.txt" are mutually exclusive. We obey robots.txt. See README.
# Every Discourse instance ships a public /search.json. Thousands of communities
# run Discourse, so adding a forum is ONE LINE here, not a new collector.
#
# This is the collector that replaces Google search, and it is strictly better at
# the job: rather than asking a search engine to FIND forum threads, we ask the
# forums directly. No key, no card, no quota.
#
# Platform support forums are the prize. They are a near-pure BUYER population —
# the poster has already paid for Shopify/WordPress/Wix, is stuck, and "is there
# someone I can just pay to do this?" is a sentence that appears constantly.
# Almost no agencies lurk there: no karma to farm, no audience to build, so the
# seller contamination that ruins r/SEO is simply absent.
# Verified live 2026-07-11. Each returns real "hire someone to build this" threads:
#   community.shopify.com  -> "Hire someone for help with Shopify store"
#   forum.bubble.io        -> "How can I hire someone in bubble to build the app"
#   meta.discourse.org     -> "Looking to hire someone to help me develop..."
# community.weebly.com is DEAD (URLError, no DNS) — do not add it back.
DISCOURSE_SITES = [
    "https://community.shopify.com",
    "https://forum.bubble.io",
    "https://forum.webflow.com",
    "https://meta.discourse.org",
]
DISCOURSE_QUERIES = [
    "hire someone", "pay someone", "need a developer", "need a designer",
    "need help with my website", "looking for someone to build",
    "not showing up on google", "need seo help",
]

# --- Stack Exchange ----------------------------------------------------------
#
# webmasters.stackexchange is a room full of buyers: "why doesn't my site rank",
# "how do I get my business on Google". People who cannot solve their own problem
# and are one bad afternoon from paying somebody. Seller contamination is ~zero —
# agencies do not answer htaccess questions for internet points.
#
# The key is FREE and lifts the quota from 300/day to 10,000/day. Verified today
# with the key already in your .env: quota_remaining 9997.
STACKEXCHANGE_SITES = ["webmasters", "wordpress"]
STACKEXCHANGE_KEY = os.getenv("STACKEXCHANGE_KEY", "").strip()
STACKEXCHANGE_QUERIES = [
    "hire someone website", "pay someone to build", "need a web developer",
    "site not ranking", "not showing up in google", "business website help",
]

# --- Bluesky -----------------------------------------------------------------
#
# searchPosts REQUIRES auth. public.api.bsky.app unauthenticated can only do
# actor (people) search, not post search. A free app password is enough:
# Settings -> App Passwords. Without it the collector skips cleanly.
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE", "").strip()
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD", "").strip()
BLUESKY_PDS = "https://bsky.social"
BLUESKY_APPVIEW = "https://public.api.bsky.app"
BLUESKY_QUERIES = [
    "need a website", "looking for a web designer", "need seo help",
    "hire a web developer",
]

# --- Mastodon ----------------------------------------------------------------

MASTODON_INSTANCES = ["mastodon.social", "mstdn.social"]
MASTODON_TAGS = ["webdesign", "smallbusiness", "seo"]

# --- Job boards --------------------------------------------------------------
#
# Freelancer.com's public API is real and free (no key for active projects).
# Upwork's RSS feeds were KILLED on 2024-08-20 and never restored — do not add
# them back. PeoplePerHour has no RSS either; it is HTML-only, so it goes
# through the scrape path and obeys robots.txt.
FREELANCER_API = "https://www.freelancer.com/api/projects/0.1/projects/active/"
FREELANCER_QUERIES = ["website design", "seo"]
PEOPLEPERHOUR_URLS = [
    "https://www.peopleperhour.com/freelance-jobs/design/website-design",
    "https://www.peopleperhour.com/freelance-jobs/marketing-seo",
]

# --- Directories (contactable stream) ----------------------------------------
#
# Yelp Fusion was REMOVED: it went paid (Starter $7.99/1k calls, plans from
# $299/mo), which violates the no-paid-API rule.
#
# OSM Overpass is the primary and the only one on by default: no key, no bill,
# and `nwr[shop][phone][!website]` is exactly "a real business with a phone
# number and no website" — the contactable half of the product.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# India only, and deliberately so. This list used to sweep the UK and US too, on
# a "leads are leads" theory. It doesn't survive contact with the actual job: an
# OSM lead is a shop with a phone number and no website, so the whole pitch is a
# cold call or a WhatsApp message in a language you share, in a timezone you are
# awake in, to someone who can meet you. A Birmingham barber is unreachable in
# practice, and every one we collected was noise in the sheet — so we no longer
# spend two minutes of Overpass budget collecting it.
#
# This is a claim about OSM leads specifically, NOT about the intent collectors.
# A Reddit or Freelancer poster is reachable from anywhere, so those stay global.
#
# COST WARNING, and it is why this list is ten cities and not forty: Overpass
# allows ~1 query per 10s and each one can take up to OVERPASS_TIMEOUT to answer,
# so every city you add is up to ~2 minutes of wall clock. Use
# `--areas "Delhi,Gurugram"` to work one market instead of the whole list.
OVERPASS_AREAS = [
    # Delhi NCR — the home market; these you can meet in person.
    "Delhi", "Gurugram", "Noida", "Faridabad", "Ghaziabad",
    # The other metros — same timezone, same languages, remote-close.
    "Bengaluru", "Mumbai", "Pune", "Hyderabad", "Chennai",
]
OVERPASS_TIMEOUT = 120

# Which country each sweep city is in. This feeds two things: the Country column
# (so you can sort a market), and phone normalisation for the WhatsApp link — a
# UK "0113 ..." number cannot become a wa.me link without knowing it is +44.
# A city passed via --areas that is not in this map still works; its country and
# WhatsApp cell just stay blank unless the number is already in +.. form.
#
# The non-IN cities are no longer swept by default (see OVERPASS_AREAS) but stay
# mapped: `--areas "London"` is still a supported one-off, and a run whose phone
# numbers silently lost their country code would be worse than no run.
AREA_COUNTRY = {
    "Delhi": "IN", "Gurugram": "IN", "Noida": "IN", "Faridabad": "IN",
    "Ghaziabad": "IN", "Bengaluru": "IN", "Mumbai": "IN", "Pune": "IN",
    "Hyderabad": "IN", "Chennai": "IN",
    "London": "GB", "Manchester": "GB", "Leeds": "GB", "Birmingham": "GB",
    "Bristol": "GB",
    "Austin": "US", "Denver": "US", "Phoenix": "US", "Nashville": "US",
}

# Google Places lost its $200/month free credit in March 2025 and now requires a
# billing card. Opt-in only (--places), OFF by default.
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
ENABLE_PLACES = _flag("ENABLE_PLACES")
PLACES_QUERIES = ["bakery in Leeds", "plumber in Manchester"]

# JustDial: HTML scraping only, no public API. It violates their ToS and they
# will block you. --justdial opt-in, OFF by default, never run it casually.
ENABLE_JUSTDIAL = _flag("ENABLE_JUSTDIAL")

# --- New domains -------------------------------------------------------------
#
# The generic "parked domain" check mostly finds squatters. What we actually want
# is someone who ALREADY PAID for Shopify/Wix/Squarespace and has not launched —
# card already out, no site live. Plus MX-but-no-A: business email set up, no
# website. Both are far cleaner signals than "parked".
WHOISDS_URL = ("https://www.whoisds.com/whois-database/"
               "newly-registered-domains/{key}/nrd")
NRD_DAYS_BACK = 2
NRD_KEYWORDS = ["bakery", "plumb", "salon", "cafe", "dental", "roofing",
                "landscap", "boutique", "clinic", "studio", "barber", "florist"]
NRD_MAX_PROBES = 40

# --- Registries --------------------------------------------------------------

COMPANIES_HOUSE_KEY = os.getenv("COMPANIES_HOUSE_KEY", "").strip()
COMPANIES_HOUSE_API = "https://api.company-information.service.gov.uk"
# Australia's ABN Lookup: free, key required but free to obtain.
ABN_GUID = os.getenv("ABN_GUID", "").strip()
ABN_API = "https://abr.business.gov.au/json/AbnDetails.aspx"
# Colorado SoS publishes free daily new-entity CSVs. No key, no rate limit.
COLORADO_SOS_CSV = ("https://data.colorado.gov/resource/4ykn-tg5h.json"
                    "?$where=entitystatus='Good Standing'&$limit=200"
                    "&$order=entityformdate DESC")

# --- Web search — OPTIONAL, AND YOU DO NOT NEED IT ----------------------------
#
# Leave GOOGLE_CSE_KEY blank and this collector skips cleanly. Nothing depends on
# it. It is here because a general web search is genuinely the widest net, but the
# free routes to one all turned out to be dead ends:
#
#   * Google CSE      — free 100/day, but the Cloud console pushes you through a
#                       billing signup. If you will not give them a card (fair),
#                       skip it.
#   * DuckDuckGo Lite — robots.txt ALLOWS it, but it silently serves an empty
#                       results page to scripts: HTTP 200, zero results, every
#                       query. Verified 2026-07-11. That is the worst possible
#                       failure mode and we will not build on it.
#   * SearX instances — 403/429 to anything that isn't a browser.
#   * Mojeek, Marginalia — robots.txt DISALLOWS /search. We obey robots.txt.
#
# What replaced it: collectors/forums.py asks the forums DIRECTLY (every Discourse
# instance ships a public /search.json), and collectors/stackexchange.py asks
# Stack Exchange directly. Instead of begging a search engine to find the threads,
# we go to where the threads live. No key, no card, no quota — and better recall.
#
# Google Programmable Search (CSE): 100 queries/day free, no card.
#   GOOGLE_CSE_KEY — enable "Custom Search API" and make a key:
#     https://console.cloud.google.com/apis/library/customsearch.googleapis.com
#     (NOT your GEMINI_API_KEY — different product, different key.)
#   GOOGLE_CSE_CX  — https://programmablesearchengine.google.com/ → create →
#     and you MUST switch ON "Search the entire web". A CSE defaults to searching
#     only the sites you list, which returns zero for every query while looking
#     completely healthy.
GOOGLE_CSE_KEY = os.getenv("GOOGLE_CSE_KEY", "").strip()
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "").strip()
# Fallback: 2,000 queries/month free, also no card.
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "").strip()

# One query = one request against a 100/day budget, so this list is the budget.
# Roughly a dozen templates, run hourly, costs ~12/100 — comfortable.
#
# The site: operators matter. A bare "need a website" returns SEO blogspam about
# needing a website. Scoping to the places where real people ASK is what makes
# the difference between a lead list and a content-marketing reading list.
SEARCH_QUERIES = [
    # Reddit, via Google — an independent route that needs no Reddit credentials.
    'site:reddit.com ("need a website" OR "looking for a web designer") '
    '("my business" OR "my shop" OR "our company")',
    'site:reddit.com ("not showing up on google" OR "not ranking") '
    '("my business" OR "my shop")',
    'site:reddit.com/r/Contractor OR site:reddit.com/r/Handyman "website"',
    'site:reddit.com/r/Dentistry OR site:reddit.com/r/Chiropractic "website"',
    # Quora — no API, real buyers, almost no agencies.
    'site:quora.com "how much does a website cost for a small business"',
    'site:quora.com ("need a website for my business" OR "hire a web designer")',
    # Platform support forums: a near-pure buyer population. "Is there someone I
    # can just pay to do this" appears constantly and no agency is lurking there.
    'site:wordpress.org/support ("hire someone" OR "pay someone") website',
    'site:community.shopify.com ("hire someone" OR "need help with my store")',
    'site:support.squarespace.com OR site:community.wix.com "hire a designer"',
    # Trade forums with no API and a proof-of-work bot wall — Google has already
    # crawled them, so we get the content without fighting the wall.
    'site:contractortalk.com OR site:lawnsite.com "website" ("need" OR "looking for")',
    # The open web: people asking in public, anywhere.
    '"just started my business" "need a website" -site:pinterest.com -"for hire"',
    '"opening" ("bakery" OR "salon" OR "gym" OR "cafe") "need a website"',
]

# --- Gemini ------------------------------------------------------------------

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_BATCH_SIZE = 8
GEMINI_TIMEOUT = 60
GEMINI_HTTP_RETRIES = 3
# Google STOPPED publishing per-model free-tier RPM in the public rate-limit doc
# (ai.google.dev/gemini-api/docs/rate-limits now says "view your limits in AI
# Studio" — they are per-account). The 5.0s in email-automation was tuned to a
# 15 RPM cap that has since moved, so do not trust it. We pace at 6s (~10 RPM),
# honour the retryDelay Google returns on a 429, and expose the knob as an env
# var so a paid-tier user can turn it down. Check your own limit at
# https://aistudio.google.com/rate-limit
GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_MIN_INTERVAL", "6.0"))
REGEN_ROUNDS = 2

# --- Scoring -----------------------------------------------------------------

# Below LOW: dropped without asking Gemini. Above HIGH: accepted without asking
# Gemini. In between: the classifier decides. LLM spend stays proportional to
# genuine ambiguity, and the cache means a re-score of an unchanged corpus is free.
BORDERLINE_LOW = 35
BORDERLINE_HIGH = 70

# Every phrase bank is English, so a non-English buyer scores 0 and used to be
# dropped before Gemini ever saw them — invisible, not rejected. They are now
# routed to the classifier instead (see intent/score.py), but that costs quota,
# and the free tier already throttles hard. This caps the bleeding: the first N
# non-English signals per run get a look, the rest wait for the next run.
# Set to 0 to turn the behaviour off entirely.
MAX_FOREIGN_TO_CLASSIFY = int(os.getenv("MAX_FOREIGN_TO_CLASSIFY", "100"))
MIN_SCORE_DEFAULT = 40
# final = RULE_WEIGHT*rule + LLM_WEIGHT*llm. The rule score survives on its own
# if Gemini is down, so an outage never looks like "no leads today".
RULE_WEIGHT = 0.4
LLM_WEIGHT = 0.6

# --- Draft -------------------------------------------------------------------

OPENER_MIN_WORDS = 25
OPENER_MAX_WORDS = 110
SIGNATURE = "Ashutosh"
