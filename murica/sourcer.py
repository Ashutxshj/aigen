"""Source Google Maps businesses in ONE US state that own their own website.

Every source returns the same target dict:
  {business_name, phone, email, rating (float|None), reviews (int),
   address, category, place_id, website, domain}

Modes, tried in order:
  1. Apify Google Maps Scraper, if APIFY_TOKEN is set (card-free, preferred).
  2. Built-in mock list, so the pipeline runs end-to-end with no keys.

Filters applied HERE (before any WHOIS spend in main.py):
  * no website / platform-profile "website" (facebook, wix, yelp, ...) -> out
  * EXCLUDED_KEYWORDS (beauty, digital marketing, tech, ...) -> out
  * famous_brands.csv hit on name or domain -> out
  * one target per registrable domain (a second location of the same
    business is the same lead)

Log phrasing note: the launcher toasts a rate-limit warning on any line matching
"Apify returned ..." or "Apify request failed", so those phrasings are reserved
for genuine failures here — the success line says "Apify OK" on purpose.
"""

import json
import os
import re
from urllib.parse import urlsplit

import requests

import brands
import config

APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

MOCK_TARGETS = [
    {"business_name": "Hendricks & Sons Law Office", "phone": "(205) 555-0142",
     "email": "", "rating": 4.6, "reviews": 87,
     "address": "1200 20th St S, Birmingham, AL", "category": "Law firm",
     "place_id": "mockA", "website": "https://www.hendrickslaw-al.com"},
    {"business_name": "Riverside Family Dental", "phone": "(256) 555-0198",
     "email": "smile@riversidefamilydental.com", "rating": 4.8, "reviews": 210,
     "address": "45 River Rd, Huntsville, AL", "category": "Dentist",
     "place_id": "mockB", "website": "http://riversidefamilydental.com/home"},
    {"business_name": "Tri-County Plumbing & Heating", "phone": "(334) 555-0177",
     "email": "", "rating": 4.4, "reviews": 63,
     "address": "88 Industrial Pkwy, Montgomery, AL", "category": "Plumber",
     "place_id": "mockC", "website": "https://tricountyplumbingal.com"},
    {"business_name": "McDonald's", "phone": "(205) 555-0100",
     "email": "", "rating": 3.9, "reviews": 1500,
     "address": "1 Fast Food Way, Birmingham, AL", "category": "Fast food restaurant",
     "place_id": "mockD", "website": "https://www.mcdonalds.com"},
    {"business_name": "Glow Beauty Salon", "phone": "(205) 555-0111",
     "email": "", "rating": 4.9, "reviews": 320,
     "address": "9 Style Ave, Birmingham, AL", "category": "Beauty salon",
     "place_id": "mockE", "website": "https://glowbeautysalon.com"},
    {"business_name": "Bama Bites Diner", "phone": "(251) 555-0155",
     "email": "", "rating": 4.5, "reviews": 140,
     "address": "301 Dauphin St, Mobile, AL", "category": "Family restaurant",
     "place_id": "mockF", "website": "https://www.facebook.com/bamabites"},
]

# Registrable domain: last two labels, except for these second-level public
# suffixes where it takes three (rare for US businesses, cheap to guard).
_MULTI_PART_SUFFIXES = {"co.uk", "org.uk", "com.au", "co.nz", "co.in", "com.mx"}


def domain_of(website: str) -> str:
    """Registrable domain from a website URL. '' if it can't be one."""
    if not website:
        return ""
    if "://" not in website:
        website = "http://" + website
    host = (urlsplit(website).hostname or "").lower().strip(".")
    if not host or "." not in host or re.fullmatch(r"[\d.]+", host):
        return ""
    labels = host.split(".")
    take = 3 if ".".join(labels[-2:]) in _MULTI_PART_SUFFIXES else 2
    return ".".join(labels[-take:])


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_rating(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _excluded_keyword(t: dict):
    """Blocklist keyword hit if this target is beauty/digital/tech etc."""
    hay = " ".join((t.get("business_name", ""), t.get("category", ""))).lower()
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _filter(targets: list) -> list:
    """One clean candidate per domain, in source order."""
    famous = brands.load()
    seen_domains, out = set(), []
    skipped = {"no_domain": 0, "platform": 0, "keyword": 0, "famous": 0, "dupe": 0}

    for t in targets:
        name = (t.get("business_name") or "").strip()
        if not name:
            continue
        t["business_name"] = name
        domain = domain_of(t.get("website") or "")
        if not domain:
            skipped["no_domain"] += 1
            continue
        if domain in config.PLATFORM_DOMAINS:
            skipped["platform"] += 1
            continue
        kw = _excluded_keyword(t)
        if kw:
            print(f"[sourcer] {name}: likely has a good site already "
                  f"(matched '{kw}') — skipped")
            skipped["keyword"] += 1
            continue
        hit = brands.match(famous, name, domain)
        if hit:
            print(f"[sourcer] {name}: famous brand (matched '{hit}') — skipped")
            skipped["famous"] += 1
            continue
        if domain in seen_domains:
            skipped["dupe"] += 1
            continue
        seen_domains.add(domain)
        t["domain"] = domain
        out.append(t)

    dropped = ", ".join(f"{v} {k}" for k, v in skipped.items() if v)
    print(f"[sourcer] {len(out)} candidate(s) kept"
          + (f" (dropped: {dropped})" if dropped else ""))
    return out


def _queries(state: str, categories: list) -> list:
    return [f"{cat} in {state}, USA" for cat in categories]


def _source_from_apify(state: str, categories: list) -> list:
    """One sync Apify actor run over the category x state queries.

    Deliberately a single direct call with a long timeout and NO retry: a retry
    on timeout would re-run a *billed* actor run. On failure, log and return [].
    """
    queries = _queries(state, categories)[: config.APIFY_MAX_SEARCHES]
    print(f"[sourcer] Apify mode: actor={config.APIFY_ACTOR_ID}, "
          f"{len(queries)} queries x {config.APIFY_MAX_PLACES_PER_SEARCH} places")
    url = APIFY_RUN_SYNC_URL.format(actor=config.APIFY_ACTOR_ID.replace("/", "~"))
    payload = {
        "searchStringsArray": queries,
        "maxCrawledPlacesPerSearch": config.APIFY_MAX_PLACES_PER_SEARCH,
        "language": "en",
        # Country lock: without it, Maps text search returns lookalike
        # businesses from anywhere in the world.
        "countryCode": "us",
        # Actor-side filter: only crawl places that HAVE a website. Saves
        # credits; the domain check in _filter still applies as belt-and-braces.
        "website": "withWebsite",
    }
    try:
        resp = requests.post(url, params={"token": config.APIFY_TOKEN},
                             json=payload, timeout=300)
    except requests.RequestException as exc:
        print(f"[sourcer] Apify request failed: {type(exc).__name__}: {exc}")
        return []
    if resp.status_code not in (200, 201):
        print(f"[sourcer] Apify returned {resp.status_code}: {resp.text[:300]}")
        return []
    try:
        items = resp.json()
    except ValueError:
        print("[sourcer] Apify response was not JSON")
        return []

    targets, no_website = [], 0
    for item in items:
        website = item.get("website") or ""
        if not website:
            no_website += 1
            continue  # nothing to age-check — not this tool's lead
        emails = item.get("emails")
        targets.append({
            "business_name": item.get("title") or item.get("name", ""),
            "phone": item.get("phone") or item.get("phoneUnformatted") or "",
            "email": (emails[0] if isinstance(emails, list) and emails
                      else item.get("email") or ""),
            "rating": _to_rating(item.get("totalScore")),
            "reviews": _to_int(item.get("reviewsCount")),
            "address": item.get("address") or "",
            "category": item.get("categoryName") or "",
            "place_id": item.get("placeId") or "",
            "website": website,
        })
    print(f"[sourcer] Apify OK: {len(items)} places "
          f"({no_website} without a website — dropped)")
    return targets


# --- category rotation -------------------------------------------------------

def _load_progress() -> dict:
    if not os.path.exists(config.PROGRESS_FILE):
        return {}
    try:
        with open(config.PROGRESS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_progress(progress: dict) -> None:
    with open(config.PROGRESS_FILE, "w", encoding="utf-8") as fh:
        json.dump(progress, fh, ensure_ascii=False, indent=1)


def categories_for(state: str, advance: bool = True) -> list:
    """The next APIFY_MAX_SEARCHES-sized slice of CATEGORIES for this state.
    progress.json remembers where each state's rotation is, so repeat runs on
    one state search NEW categories instead of re-billing the same ones."""
    n = max(1, config.APIFY_MAX_SEARCHES)
    progress = _load_progress()
    start = int(progress.get(state, 0)) % len(config.CATEGORIES)
    doubled = config.CATEGORIES + config.CATEGORIES
    cats = doubled[start:start + n]
    if advance:
        progress[state] = (start + n) % len(config.CATEGORIES)
        _save_progress(progress)
    return cats


def source_targets(state: str, mock: bool = False) -> list:
    """De-duplicated, filtered own-website candidates for one state."""
    if mock:
        print("[sourcer] mock mode — using built-in demo targets")
        raw = MOCK_TARGETS
    elif config.APIFY_TOKEN:
        cats = categories_for(state)
        print(f"[sourcer] APIFY_TOKEN set — sweeping: {', '.join(cats)}")
        raw = _source_from_apify(state, cats)
    else:
        print("[sourcer] no APIFY_TOKEN — using built-in demo targets")
        raw = MOCK_TARGETS

    targets = _filter(raw)
    if config.MAX_TARGETS > 0:
        targets = targets[: config.MAX_TARGETS]
    print(f"[sourcer] {len(targets)} unique own-website candidate(s) for '{state}'")
    return targets
