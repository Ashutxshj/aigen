"""Drop DM candidates whose Instagram is already active — they don't need us.

A business posting reels near-daily has content handled; the pitch lands on
someone who is drowning, not someone with a system. One batched Apify
Instagram-profile call per run (all handles at once) returns each profile's
latest posts; from their timestamps we estimate a posts-per-week rate and drop
anyone at or above ACTIVE_POSTS_PER_WEEK.

The same call is what finally enforces "public profiles only": private and
non-existent accounts are dropped too — a DM request nobody sees is not a lead.

Fail open on infrastructure: if the actor call itself fails, every candidate is
kept. Losing one filter beats losing the whole run.
"""

from datetime import datetime, timezone

import requests

import config

APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def _timestamps(profile: dict) -> list:
    """Aware datetimes of this profile's latest posts, newest first."""
    stamps = []
    for post in profile.get("latestPosts") or []:
        raw = str(post.get("timestamp") or "").strip()
        if not raw:
            continue
        try:
            stamps.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            continue
    return sorted(stamps, reverse=True)


def posts_per_week(profile: dict) -> float:
    """Posting rate over the profile's latest posts. 0.0 for a quiet page."""
    stamps = _timestamps(profile)
    if len(stamps) < 2:
        return 0.0
    span_days = (stamps[0] - stamps[-1]).total_seconds() / 86400
    if span_days <= 0:
        return float("inf")   # a whole page of posts on one day — very active
    return (len(stamps) - 1) / span_days * 7


def _fetch_profiles(handles: list) -> dict | None:
    """{username_lower: profile_dict} via one batched actor run; None on failure."""
    url = APIFY_RUN_SYNC_URL.format(
        actor=config.IG_PROFILE_ACTOR_ID.replace("/", "~"))
    try:
        resp = requests.post(url, params={"token": config.APIFY_TOKEN},
                             json={"usernames": handles}, timeout=300)
    except requests.RequestException as exc:
        print(f"[ig] Apify request failed: {type(exc).__name__}: {exc}")
        return None
    if resp.status_code not in (200, 201):
        print(f"[ig] Apify returned {resp.status_code}: {resp.text[:300]}")
        return None
    try:
        items = resp.json()
    except ValueError:
        print("[ig] Apify response was not JSON")
        return None
    out = {}
    for item in items:
        username = str(item.get("username") or "").strip().lstrip("@").lower()
        if username:
            out[username] = item
    return out


def filter_pool(targets: list) -> list:
    """Targets minus already-active, private, and non-existent profiles.

    Skipped entirely (all kept) when there is no APIFY_TOKEN — the check costs
    a paid actor run, and without it the old behaviour is the only option.
    """
    if not targets or not config.APIFY_TOKEN:
        return targets

    handles = [str(t.get("instagram") or "").lstrip("@") for t in targets]
    print(f"[ig] checking {len(handles)} profiles for activity (one Apify call)")
    profiles = _fetch_profiles(handles)
    if profiles is None:
        print("[ig] profile check unavailable — keeping all candidates")
        return targets

    kept = []
    for t in targets:
        handle = str(t.get("instagram") or "").lstrip("@").lower()
        profile = profiles.get(handle)
        if profile is None:
            print(f"[ig] @{handle}: profile not found — dropped")
            continue
        if profile.get("private"):
            print(f"[ig] @{handle}: private profile — dropped")
            continue
        rate = posts_per_week(profile)
        if rate >= config.ACTIVE_POSTS_PER_WEEK:
            print(f"[ig] @{handle}: ~{rate:.1f} posts/week — already active, dropped")
            continue
        print(f"[ig] @{handle}: ~{rate:.1f} posts/week — needs help, kept")
        kept.append(t)
    return kept
