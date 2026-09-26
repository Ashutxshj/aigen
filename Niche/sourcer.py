"""Source Google Maps businesses in ONE chosen niche that have NO website.

Every source returns the same target dict:
  {business_name, phone, email, rating (float|None), reviews (int),
   address, category, place_id}

Modes, tried in order:
  1. Apify Google Maps Scraper, if APIFY_TOKEN is set (card-free, preferred).
  2. Google Places API (New) Text Search, if GOOGLE_PLACES_API_KEY is set.
  3. Built-in mock list, so the pipeline runs end-to-end with no keys.

Log phrasing note: the launcher toasts a rate-limit warning on any line matching
"Apify returned ..." or "Apify request failed", so those phrasings are reserved
for genuine failures here — the success line says "Apify OK" on purpose.
"""

import time

import requests

import config

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

MOCK_TARGETS = [
    {"business_name": "Spice Route Family Restaurant", "phone": "+91 98110 44444",
     "email": "", "rating": 4.5, "reviews": 620,
     "address": "Rajouri Garden, New Delhi", "category": "Restaurant", "place_id": "mockA"},
    {"business_name": "Nirvana Veg Kitchen", "phone": "+91 98990 77777",
     "email": "nirvanaveg@gmail.com", "rating": 4.2, "reviews": 210,
     "address": "Sector 62, Noida", "category": "Restaurant", "place_id": "mockB"},
    {"business_name": "Tandoor Tales", "phone": "+91 99530 88888",
     "email": "", "rating": 4.7, "reviews": 1340,
     "address": "Cyber Hub, Gurgaon", "category": "North Indian restaurant", "place_id": "mockC"},
]


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
    """Blocklist keyword hit if this target SELLS digital/marketing services."""
    hay = " ".join((t.get("business_name", ""), t.get("category", ""))).lower()
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _dedupe(targets: list) -> list:
    """One target per place (place_id, else name+address); drop nameless entries
    and digital-service sellers."""
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
            print(f"[sourcer] {name}: digital-service seller (matched '{kw}') — skipped")
            continue
        seen.add(key)
        t["business_name"] = name
        out.append(t)
    return out


def _queries(niche: str) -> list:
    return [f"{niche} in {city}" for city in config.TARGET_CITIES]


def _source_from_apify(niche: str) -> list:
    """One sync Apify actor run over the niche x city queries.

    Deliberately a single direct call with a long timeout and NO retry: a retry
    on timeout would re-run a *billed* actor run. On failure, log and return [].
    """
    queries = _queries(niche)[: config.APIFY_MAX_SEARCHES]
    print(f"[sourcer] Apify mode: actor={config.APIFY_ACTOR_ID}, "
          f"{len(queries)} queries x {config.APIFY_MAX_PLACES_PER_SEARCH} places")
    url = APIFY_RUN_SYNC_URL.format(actor=config.APIFY_ACTOR_ID.replace("/", "~"))
    payload = {
        "searchStringsArray": queries,
        "maxCrawledPlacesPerSearch": config.APIFY_MAX_PLACES_PER_SEARCH,
        "language": "en",
        # Country lock: without it, Maps text search returns lookalike
        # businesses from anywhere in the world.
        "countryCode": "in",
        # Actor-side filter: only crawl places with no website. Saves credits;
        # the client-side check below still applies as belt-and-braces.
        "website": "withoutWebsite",
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

    targets, has_website = [], 0
    for item in items:
        if item.get("website"):
            has_website += 1
            continue  # already online — not our lead
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
        })
    print(f"[sourcer] Apify OK: {len(items)} places "
          f"({has_website} with a website — dropped)")
    return targets


def _source_from_places(niche: str) -> list:
    """Google Places Text Search (New), following pagination, no-website only."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.websiteUri,places.rating,"
            "places.userRatingCount,places.nationalPhoneNumber,"
            "places.internationalPhoneNumber,places.formattedAddress,"
            "places.primaryTypeDisplayName,nextPageToken"
        ),
    }
    results = []
    for query in _queries(niche):
        print(f"[sourcer] querying Places: {query}")
        page_token = None
        for _ in range(3):  # max 3 pages (~60 results) per query
            body = {"textQuery": query}
            if page_token:
                body["pageToken"] = page_token
            try:
                resp = requests.post(PLACES_SEARCH_URL, json=body, headers=headers,
                                     timeout=config.REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                print(f"[sourcer] Places API unreachable for '{query}': {exc}")
                break
            if resp.status_code != 200:
                print(f"[sourcer] Places API {resp.status_code} for '{query}': "
                      f"{resp.text[:200]}")
                break
            data = resp.json()
            for place in data.get("places", []):
                if place.get("websiteUri"):
                    continue  # has a website — not our lead
                results.append({
                    "business_name": place.get("displayName", {}).get("text", ""),
                    "phone": place.get("nationalPhoneNumber")
                             or place.get("internationalPhoneNumber") or "",
                    "email": "",  # Places API does not expose emails
                    "rating": _to_rating(place.get("rating")),
                    "reviews": _to_int(place.get("userRatingCount")),
                    "address": place.get("formattedAddress", ""),
                    "category": place.get("primaryTypeDisplayName", {}).get("text", ""),
                    "place_id": place.get("id", ""),
                })
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(1)  # token needs a moment to become valid
        time.sleep(0.3)
    return results


def source_targets(niche: str, mock: bool = False) -> list:
    """De-duplicated no-website places for one niche."""
    if mock:
        print("[sourcer] mock mode — using built-in demo targets")
        raw = MOCK_TARGETS
    elif config.APIFY_TOKEN:
        print("[sourcer] APIFY_TOKEN set — sourcing via Apify Google Maps Scraper")
        raw = _source_from_apify(niche)
    elif config.GOOGLE_PLACES_API_KEY:
        print("[sourcer] sourcing via Google Places API")
        raw = _source_from_places(niche)
    else:
        print("[sourcer] no API token — using built-in demo targets")
        raw = MOCK_TARGETS

    targets = _dedupe(raw)
    if config.MAX_TARGETS > 0:
        targets = targets[: config.MAX_TARGETS]
    print(f"[sourcer] {len(targets)} unique no-website places for '{niche}'")
    return targets
