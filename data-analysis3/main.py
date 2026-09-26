"""Orchestrator: pick category -> source Maps places with no real website ->
STRICT VALIDATION GATE -> classify Goldenrod / New Bark -> Projects/leads_master.xlsx.

Leads land in the ONE master workbook shared by every repo (master_registry.py).
There is no output/ folder and no per-run report: businesses already in the
master are skipped by upsert(), so re-running never duplicates a lead.

Lead Type is the quality axis (Goldenrod = rating >= 4.5 AND 500+ reviews).
Reachability is implied by the master's Instagram column: a handle means you can
DM them, a blank means phone-only. The two are never merged into one tier string
— `stats` is seeded with exactly the two Lead Type keys, so a third would
KeyError on `stats[lead_type] += 1`.

DM mode (--dm-out): instead of the master-report flow, source ONE category,
keep only Instagram-reachable businesses, take the best DM_TOP (default 10)
from a pool of DM_POOL (default 30) candidates, and write a small sheet of
clickable profile + ig.me DM links. The picked rows still land in the master,
so the next run brings 10 FRESH businesses instead of the same ones.

Usage:
  python main.py                 # full run (Apify / Places API / seed_places.csv)
  python main.py --mock          # built-in demo targets, no API keys needed
  python main.py --limit 25      # cap number of sourced targets
  python main.py --no-email      # build the report but skip Resend delivery
  python main.py --category 3    # preselect a business category (skips the menu)
  python main.py --category-name "cafe" --dm-out leads.xlsx   # the DM sheet
  python main.py --list-categories                            # for UIs
"""

import argparse
import os
import sys

import config
import dm_sheet
import ig_activity
import master_registry
from delivery import send_master
from target_sourcer import source_targets


def pick_category(preselected: int | None) -> str | None:
    """Numbered category menu. Returns the chosen category, or None for all."""
    categories = config.BUSINESS_CATEGORIES
    if preselected is not None:
        if preselected == 0:
            print("[main] --category 0 -> ALL categories")
            return None
        if 1 <= preselected <= len(categories):
            print(f"[main] --category {preselected} -> '{categories[preselected - 1]}'")
            return categories[preselected - 1]
        print(f"[main] --category {preselected} out of range — using ALL categories")
        return None

    print("\nWhich business category should this run target?")
    for i, cat in enumerate(categories, 1):
        print(f"  {i:2d}. {cat}")
    print("   0. all categories")
    while True:
        try:
            raw = input("Enter a number [0]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[main] no selection — using ALL categories")
            return None
        if raw in ("", "0"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(categories):
            choice = categories[int(raw) - 1]
            print(f"[main] targeting category: {choice}")
            return choice
        print(f"Invalid choice '{raw}' — enter 0-{len(categories)}")


def classify(target: dict) -> str:
    """Goldenrod iff rating >= 4.5 AND 500+ reviews; everything else is New Bark."""
    rating = target.get("rating")
    reviews = target.get("reviews") or 0
    if (rating is not None
            and rating >= config.GOLDENROD_MIN_RATING
            and reviews >= config.GOLDENROD_MIN_REVIEWS):
        return config.LEAD_TYPE_GOLDENROD
    return config.LEAD_TYPE_NEW_BARK


def presence_label(target: dict) -> str:
    """How we can actually reach this business, most useful channel first."""
    if target.get("instagram"):
        return config.PRESENCE_INSTAGRAM
    if target.get("social_url"):
        return config.PRESENCE_FACEBOOK
    return config.PRESENCE_PHONE_ONLY


def run_dm(category: str, out_path: str, top: int, mock: bool) -> int:
    """The DM-sheet pipeline: one category -> Instagram-reachable only ->
    best `top` of a DM_POOL-candidate pool -> clickable sheet at out_path.
    Returns 0 even when empty — an empty sheet is a result, not a failure."""
    targets = source_targets(mock=mock, category=category)

    # Businesses already in the master were already DMed (or at least sheeted)
    # — skip them so every run yields fresh handles. Mock runs skip the filter.
    if not mock:
        known = master_registry.load_keys()
        if known:
            before = len(targets)
            targets = [t for t in targets if not (_master_keys(t) & known)]
            if before - len(targets):
                print(f"[dm] {before - len(targets)} already in the master — skipped")

    ig = [t for t in targets if t.get("instagram")]
    print(f"[dm] {len(ig)} Instagram-reachable candidates")
    pool = ig[: config.DM_POOL]

    # One batched profile check: drop private/dead accounts and anyone already
    # posting near-daily — an active page will never buy content help. Mock
    # runs skip it (the check is a paid actor call).
    if not mock:
        pool = ig_activity.filter_pool(pool)
        print(f"[dm] {len(pool)} candidates after the activity check")

    # Best first: Goldenrod quality, then the most-reviewed. The pool cap keeps
    # the pick honest — 10 great handles from 30 candidates, not from 300 stale.
    pool.sort(key=lambda t: (classify(t) != config.LEAD_TYPE_GOLDENROD,
                             -(t.get("reviews") or 0)))
    picked = pool[:top]
    if not picked:
        print("[dm] 0 Instagram-reachable businesses this run — no sheet written")
        return 0

    dm_sheet.write(out_path, picked)
    print(f"[dm] wrote {len(picked)} DM lead(s) -> {out_path}")
    for t in picked:
        print(f"[dm]   {t['business_name']}: @{t['instagram'].lstrip('@')} "
              f"({t.get('category') or '?'}, {t.get('address') or '?'})")

    # Record them in the master so the next run starts past them.
    if mock and not os.getenv("MASTER_FILE"):
        print("[dm] mock run — not touching the real master file")
    else:
        rows = [{
            "Business Name": t["business_name"],
            "Category": t.get("category") or "",
            "Lead Type": classify(t),
            "Has_Website": False,
            "Phone Number": t.get("phone") or "",
            "Email Address": "",
            "Instagram": t.get("instagram") or "",
            "Rating": t.get("rating") if t.get("rating") is not None else "",
            "Reviews": t.get("reviews") or 0,
            master_registry.BULLETS_COLUMN: master_registry.no_website_bullets(
                t.get("category"), t.get("rating"), t.get("reviews") or 0,
                t.get("instagram")),
        } for t in picked]
        added = master_registry.upsert(rows)
        print(f"[dm] {added} recorded in the master file")
    return 0


def _master_keys(target: dict) -> set[str]:
    """Identity keys for a sourcer target, in master-column terms."""
    return master_registry.identity_keys({
        "Business Name": target.get("business_name", ""),
        "Phone Number": target.get("phone", ""),
        "Instagram": target.get("instagram", ""),
        "Email Address": "",
    })


def run(mock: bool, limit: int, no_email: bool, category: str | None = None) -> int:
    # --- Stage 1: source places with no real website ---
    targets = source_targets(mock=mock, category=category)

    # Businesses already in the master are dropped BEFORE --limit so the cap
    # fills with fresh leads. Mock runs skip it so smoke tests stay green.
    if not mock:
        known = master_registry.load_keys()
        if known:
            before = len(targets)
            targets = [t for t in targets if not (_master_keys(t) & known)]
            if before - len(targets):
                print(f"[main] {before - len(targets)} businesses already in the "
                      "master file — skipped")

    # NOTE: --limit truncates SOURCED targets, before we know which ones carry an
    # Instagram handle. Cap it and you may discard most of your DM-reachable
    # leads while keeping phone-only ones. The Apify credits are spent either
    # way, so prefer no --limit on a real run.
    if limit > 0:
        targets = targets[:limit]
    if not targets:
        print("[main] no targets sourced — nothing to do")
        return 1

    rows: list[dict] = []
    stats = {"sourced": len(targets), "no_contact": 0,
             config.LEAD_TYPE_GOLDENROD: 0, config.LEAD_TYPE_NEW_BARK: 0}

    for i, target in enumerate(targets, 1):
        name = target["business_name"]
        phone = target.get("phone") or ""
        instagram = target.get("instagram") or ""
        social = target.get("social_url") or ""

        # --- Stage 2: STRICT VALIDATION GATE ---
        # A lead we cannot contact is not a lead. Keep it if there is any channel:
        # an Instagram handle, some other social page, or a phone number.
        if not instagram and not social and not phone:
            print(f"[main] ({i}/{len(targets)}) {name}: no social AND no phone — discarded")
            stats["no_contact"] += 1
            continue

        # --- Stage 3: tier + reachability classification ---
        lead_type = classify(target)
        stats[lead_type] += 1
        presence = presence_label(target)
        rating = target.get("rating")
        print(f"[main] ({i}/{len(targets)}) {name}: {lead_type} / {presence} "
              f"(rating={rating if rating is not None else 'n/a'}, "
              f"reviews={target.get('reviews') or 0}, "
              f"ig={instagram or '-'}, phone={phone or '-'})")

        reviews = target.get("reviews") or 0
        rows.append({
            "Business Name": name,
            "Category": target.get("category") or "",
            "Lead Type": lead_type,
            "Has_Website": False,
            "Phone Number": phone,
            "Email Address": "",
            "Instagram": instagram,
            "Rating": rating if rating is not None else "",
            "Reviews": reviews,
            master_registry.BULLETS_COLUMN: master_registry.no_website_bullets(
                target.get("category"), rating, reviews, instagram),
            # Not a master column — used for the local sort only.
            "_presence": presence,
        })

    # Reachability dominates: a 5-star Goldenrod we can only phone is useless to
    # a DM-only workflow, so it sorts below every socially-reachable New Bark.
    presence_rank = {config.PRESENCE_INSTAGRAM: 0, config.PRESENCE_FACEBOOK: 1,
                     config.PRESENCE_PHONE_ONLY: 2}
    rows.sort(key=lambda r: (presence_rank.get(r["_presence"], 3),
                             r["Lead Type"] != config.LEAD_TYPE_GOLDENROD,
                             -(r["Reviews"] or 0)))
    for row in rows:
        row.pop("_presence", None)

    # --- Stage 4: append to the ONE master workbook ---
    # A --mock run must never pollute the real master with fictional businesses.
    # Overriding MASTER_FILE (a scratch path) is the explicit opt-in used by tests.
    if mock and not os.getenv("MASTER_FILE"):
        print("[main] mock run — not touching the real master file")
        added = 0
    else:
        added = master_registry.upsert(rows)

    goldenrod = stats[config.LEAD_TYPE_GOLDENROD]
    new_bark = stats[config.LEAD_TYPE_NEW_BARK]
    dm_ready = sum(1 for r in rows if r["Instagram"])
    print(
        f"\n[main] done: sourced={stats['sourced']} no_contact={stats['no_contact']} "
        f"kept={len(rows)} added={added} (Goldenrod={goldenrod}, New Bark={new_bark}) "
        f"— {dm_ready} reachable by Instagram DM"
    )
    print(f"[main] master -> {master_registry.MASTER_FILE}")
    if len(rows) - added:
        print(f"[main] {len(rows) - added} were already in the master file")

    # --- Stage 5: deliver the master TO THE OPERATOR (never to a prospect) ---
    if no_email:
        print("[main] --no-email set — skipping delivery")
    elif not added:
        print("[main] 0 new leads — skipping delivery")
    else:
        send_master(added, goldenrod=goldenrod, new_bark=new_bark, dm_ready=dm_ready)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Instagram-reachable business leads pipeline (India-wide)")
    parser.add_argument("--mock", action="store_true", help="use built-in demo targets")
    parser.add_argument("--limit", type=int, default=0, help="cap sourced targets")
    parser.add_argument("--no-email", action="store_true", help="skip Resend delivery")
    parser.add_argument("--category", type=int, default=None,
                        help="business category number (1-based, see startup menu); "
                             "omit for the interactive menu, 0 for all")
    parser.add_argument("--category-name", default=None,
                        help="business category by name (any Maps search term); "
                             "overrides --category")
    parser.add_argument("--dm-out", default=None, metavar="XLSX",
                        help="DM mode: write the top Instagram DM leads sheet "
                             "here instead of the master-report flow")
    parser.add_argument("--top", type=int, default=config.DM_TOP,
                        help=f"DM mode: how many leads in the sheet "
                             f"(default {config.DM_TOP})")
    parser.add_argument("--list-categories", action="store_true",
                        help="print BUSINESS_CATEGORIES one per line and exit")
    args = parser.parse_args()

    if args.list_categories:
        print("\n".join(config.BUSINESS_CATEGORIES))
        sys.exit(0)

    if args.dm_out:
        chosen = args.category_name or pick_category(args.category)
        if not chosen:
            parser.error("DM mode needs one category (--category-name or --category N)")
        sys.exit(run_dm(category=chosen.strip().lower(), out_path=args.dm_out,
                        top=args.top, mock=args.mock))

    chosen = args.category_name or pick_category(args.category)
    sys.exit(run(mock=args.mock, limit=args.limit, no_email=args.no_email,
                 category=chosen))
