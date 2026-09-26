"""Stage 1 — Sourcing targets: Indian businesses whose ONLY web presence is social.

Every source returns Google-Maps-shaped place records, which are then run through
`web_presence.classify()`:

  * real website  -> dropped (already online; that business belongs to /scraper)
  * social-only   -> KEPT, with the Instagram handle extracted
  * no presence   -> KEPT, flagged "Phone only"

Contact info, star rating and review count come straight from the Maps listing —
there is no site to scrape.

Target dict shape (used by every mode):
  {business_name, phone, rating (float|None), reviews (int), address, category,
   place_id, web_presence ("real"|"social"|"none"), instagram ("@x"|""),
   social_url}

Four modes, tried in order:
  1. Apify Google Maps Scraper, if APIFY_TOKEN is set (card-free, preferred).
  2. Google Places API (New) Text Search, if GOOGLE_PLACES_API_KEY is set.
     WEAK for this repo — see _places_text_search().
  3. seed_places.csv — plug in any Maps-scraper export.
  4. Built-in mock list, so the pipeline runs end-to-end with no keys.
"""

import csv
import os
import re
import time

import requests

import config
import http_client
import web_presence

# Whole-word match so "spa" kills "Bliss Spa" but not "Spanish Tapas".
_BEAUTY_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in config.BEAUTY_FASHION_KEYWORDS)
    + r")\b", re.IGNORECASE)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

# Fictional businesses with fictional handles, on purpose. /scraper's mock list
# points at livspace.com and haldirams.com, and those real corporate inboxes
# ended up harvested into its real output CSVs. Never put a live company here.
MOCK_TARGETS = [
    # social-only -> kept, handle extracted
    {"business_name": "Bloom Cafe", "phone": "+91 98110 12345",
     "rating": 4.8, "reviews": 812, "address": "Karol Bagh, New Delhi",
     "category": "Cafe", "place_id": "mock1",
     "website": "https://www.instagram.com/bloomcafedelhi/"},
    # real website -> dropped
    {"business_name": "Anand Sweets", "phone": "+91 98990 55555",
     "rating": 4.6, "reviews": 1450, "address": "Sector 18, Noida",
     "category": "Restaurant", "place_id": "mock2",
     "website": "https://anandsweets.example.com"},
    # no web presence, has phone -> kept, "Phone only"
    {"business_name": "Iron Core Gym", "phone": "+91 99530 22222",
     "rating": 4.9, "reviews": 133, "address": "Sector 15, Faridabad",
     "category": "Gym", "place_id": "mock3", "website": ""},
    # facebook-only -> kept, "Facebook page", no Instagram handle
    {"business_name": "Petal & Vine Florist", "phone": "",
     "rating": 4.4, "reviews": 61, "address": "Greater Kailash, New Delhi",
     "category": "Florist", "place_id": "mock4",
     "website": "https://www.facebook.com/petalvinegk"},
    # no handle AND no phone -> discarded by the strict gate in main.py
    {"business_name": "Quiet Corner Bakery", "phone": "",
     "rating": 4.7, "reviews": 240, "address": "DLF Phase 3, Gurgaon",
     "category": "Bakery", "place_id": "mock5", "website": ""},
]


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_rating(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _excluded_keyword(t: dict) -> str | None:
    """Return the blocklist keyword hit if this target SELLS tech/marketing services."""
    hay = " ".join((t.get("business_name", ""), t.get("category", ""))).lower()
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _beauty_keyword(t: dict) -> str | None:
    """The beauty-vertical word hit, if this target is a salon/nails/spa/makeup
    business. They are already content-efficient on Instagram — not a prospect
    for content or website work, so they are dropped at the source."""
    hay = " ".join((t.get("business_name", ""), t.get("category", "")))
    m = _BEAUTY_RE.search(hay)
    return m.group(1) if m else None


def _dedupe(targets: list[dict]) -> list[dict]:
    """One target per place (place_id, else name+address); drop nameless entries,
    tech/digital-marketing sellers (peers, not prospects) and the beauty
    vertical (already Instagram-efficient)."""
    seen, out = set(), []
    for t in targets:
        name = (t.get("business_name") or "").strip()
        if not name:
            continue
        key = t.get("place_id") or f"{name.lower()}|{(t.get('address') or '').lower()}"
        if key in seen:
            continue
        kw = _excluded_keyword(t)
        if kw:
            print(f"[sourcer] {name}: tech/marketing seller (matched '{kw}') — skipped")
            continue
        kw = _beauty_keyword(t)
        if kw:
            print(f"[sourcer] {name}: beauty vertical (matched '{kw}') — skipped")
            continue
        seen.add(key)
        t["business_name"] = name
        out.append(t)
    return out


def _presence_fields(*url_candidates: str) -> dict:
    """Shared shape for the three presence keys every target dict carries."""
    urls = [u for u in url_candidates if u]
    return {
        "web_presence": web_presence.classify(*urls),
        "instagram": web_presence.instagram_handle(*urls) or "",
        "social_url": web_presence.social_url(*urls),
    }


def _places_text_search(query: str, api_key: str) -> list[dict]:
    """One Text Search (New) query, following nextPageToken pagination.

    WEAK SOURCE for this repo. The Places API exposes only `websiteUri` and has
    no social fields at all, so a social-only business is visible to us *only*
    when it happens to have put its Instagram URL in that one slot. A business
    that left the website field blank is indistinguishable from a true
    no-presence one and lands in "none". Prefer Apify.
    """
    results, page_token = [], None
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.websiteUri,places.rating,"
            "places.userRatingCount,places.nationalPhoneNumber,"
            "places.internationalPhoneNumber,places.formattedAddress,"
            "places.primaryTypeDisplayName,nextPageToken"
        ),
    }
    for _ in range(3):  # max 3 pages (~60 results) per query
        body = {"textQuery": query}
        if page_token:
            body["pageToken"] = page_token
        resp = http_client.post(PLACES_SEARCH_URL, json=body, headers=headers)
        if resp is None:
            print(f"[sourcer] Places API unreachable for '{query}' after retries")
            break
        if resp.status_code != 200:
            print(f"[sourcer] Places API {resp.status_code} for '{query}': {resp.text[:200]}")
            break
        data = resp.json()
        for place in data.get("places", []):
            presence = _presence_fields(place.get("websiteUri") or "")
            if presence["web_presence"] == web_presence.REAL:
                continue  # has a real website — not our lead
            address = place.get("formattedAddress", "")
            results.append({
                "business_name": place.get("displayName", {}).get("text", ""),
                "phone": place.get("nationalPhoneNumber")
                         or place.get("internationalPhoneNumber") or "",
                "rating": _to_rating(place.get("rating")),
                "reviews": _to_int(place.get("userRatingCount")),
                "address": address,
                "category": place.get("primaryTypeDisplayName", {}).get("text", ""),
                "place_id": place.get("id", ""),
                **presence,
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)  # token needs a moment to become valid
    return results


def _search_queries(category: str | None = None) -> list[str]:
    """The category x city cross-product used by every keyword-based source.

    Category-major order: every city appears before any category repeats, so a
    small APIFY_MAX_SEARCHES cap spreads across the whole country instead of
    being spent entirely on Delhi.
    """
    categories = [category] if category else config.BUSINESS_CATEGORIES
    return [f"{cat} in {city}"
            for cat in categories
            for city in config.TARGET_CITIES]


def _source_from_places(api_key: str, category: str | None) -> list[dict]:
    targets = []
    for query in _search_queries(category):
        print(f"[sourcer] querying Places: {query}")
        targets.extend(_places_text_search(query, api_key))
        time.sleep(0.3)
    return targets


def _apify_url_candidates(item: dict) -> list[str]:
    """Every field that might carry this place's web/social link.

    The actor's output shape for socials is not contractual: `website` is the
    Maps website slot (where Indian SMBs very often paste their Instagram), while
    `instagrams`/`facebooks` are arrays that only appear when contact enrichment
    ran. Read the union rather than betting on one field.

    Deliberately EXCLUDES `item["url"]` — that is the google.com/maps listing
    URL, and feeding it in would classify every single place as `real`.
    """
    candidates = [item.get("website") or ""]
    for key in ("instagrams", "facebooks"):
        value = item.get(key)
        if isinstance(value, list):
            candidates.extend(str(v) for v in value if v)
        elif isinstance(value, str) and value:
            candidates.append(value)
    return [c for c in candidates if c]


def _source_from_apify(category: str | None) -> list[dict]:
    """Run the Apify Google Maps actor and pull its dataset in one sync call.

    Deliberately NOT routed through http_client's retrying request(): a retry on
    timeout would re-run a *billed* actor. One direct call, long timeout, no retry;
    on any failure we log and return [] rather than risk a duplicate charged run.
    """
    queries = _search_queries(category)[: config.APIFY_MAX_SEARCHES]
    print(f"[sourcer] Apify mode: actor={config.APIFY_ACTOR_ID}, "
          f"{len(queries)} queries x {config.APIFY_MAX_PLACES_PER_SEARCH} places")
    url = APIFY_RUN_SYNC_URL.format(actor=config.APIFY_ACTOR_ID.replace("/", "~"))
    payload = {
        "searchStringsArray": queries,
        "maxCrawledPlacesPerSearch": config.APIFY_MAX_PLACES_PER_SEARCH,
        "language": "en",
        # Without a country lock, Maps text search returns lookalike businesses
        # from anywhere in the world (observed: US agencies in a "Delhi" run).
        "countryCode": "in",
        # MUST be allPlaces. scraper2 passes "withoutWebsite", which makes the
        # actor drop every place carrying a website field — including the
        # social-only businesses that put their Instagram URL there, i.e. exactly
        # the leads this repo exists to find. We take all places and classify
        # client-side. Costs more credits: keep APIFY_MAX_SEARCHES tight.
        "website": "allPlaces",
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

    targets = []
    tally = {web_presence.REAL: 0, web_presence.SOCIAL: 0, web_presence.NONE: 0}
    for item in items:
        presence = _presence_fields(*_apify_url_candidates(item))
        tally[presence["web_presence"]] += 1
        if presence["web_presence"] == web_presence.REAL:
            continue  # already online — /scraper's lead, not ours
        # No NCR gate: countryCode=in locks results to India, and DM outreach
        # is delivered remotely, so every Indian city is equally workable.
        targets.append({
            "business_name": item.get("title") or item.get("name", ""),
            "phone": item.get("phone") or item.get("phoneUnformatted") or "",
            "rating": _to_rating(item.get("totalScore")),
            "reviews": _to_int(item.get("reviewsCount")),
            "address": item.get("address") or "",
            "category": item.get("categoryName") or "",
            "place_id": item.get("placeId") or "",
            **presence,
        })
    print(f"[sourcer] Apify returned {len(items)} places "
          f"({tally[web_presence.REAL]} with a real website — dropped, "
          f"{tally[web_presence.SOCIAL]} social-only, "
          f"{tally[web_presence.NONE]} no web presence)")
    return targets


def _source_from_seed_file(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    targets = []
    for r in rows:
        presence = _presence_fields(r.get("website", ""), r.get("instagram", ""))
        if presence["web_presence"] == web_presence.REAL:
            continue
        targets.append({
            "business_name": r.get("business_name", ""),
            "phone": r.get("phone", ""),
            "rating": _to_rating(r.get("rating")),
            "reviews": _to_int(r.get("reviews")),
            "address": r.get("address", ""),
            "category": r.get("category", ""),
            "place_id": r.get("place_id", ""),
            **presence,
        })
    return targets


def _source_from_mock() -> list[dict]:
    """Mock targets run through the same classifier as every real source, so
    --mock genuinely exercises the real/social/none branches."""
    targets = []
    for m in MOCK_TARGETS:
        presence = _presence_fields(m.get("website", ""))
        if presence["web_presence"] == web_presence.REAL:
            print(f"[sourcer] {m['business_name']}: has a real website — dropped")
            continue
        targets.append({k: v for k, v in m.items() if k != "website"} | presence)
    return targets


def source_targets(mock: bool = False, category: str | None = None) -> list[dict]:
    """Return de-duplicated place records with no real website, across India.

    `category` (one of config.BUSINESS_CATEGORIES, picked at the startup menu)
    narrows keyword-based sources to that category; None sweeps all of them.
    Seed-file and mock modes have no category dimension and ignore it.
    """
    if category:
        print(f"[sourcer] category filter: {category}")
    if mock:
        print("[sourcer] mock mode — using built-in demo targets")
        raw = _source_from_mock()
    elif config.APIFY_TOKEN:
        print("[sourcer] APIFY_TOKEN set — sourcing via Apify Google Maps Scraper")
        raw = _source_from_apify(category)
    elif config.GOOGLE_PLACES_API_KEY:
        print("[sourcer] sourcing via Google Places API (weak: no social fields)")
        raw = _source_from_places(config.GOOGLE_PLACES_API_KEY, category)
    elif os.path.exists(config.SEED_FILE):
        print(f"[sourcer] no API token — reading {config.SEED_FILE}")
        raw = _source_from_seed_file(config.SEED_FILE)
    else:
        print("[sourcer] no API token and no seed_places.csv — using demo targets")
        raw = _source_from_mock()

    targets = _dedupe(raw)
    if config.MAX_TARGETS > 0:
        targets = targets[: config.MAX_TARGETS]
    reachable = sum(1 for t in targets if t.get("instagram"))
    print(f"[sourcer] {len(targets)} unique places with no real website "
          f"({reachable} with an Instagram handle)")
    return targets
