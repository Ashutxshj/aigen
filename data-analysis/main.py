"""Orchestrator: pick category -> source -> sitemap last-updated filter ->
scrape contacts -> STRICT VALIDATION GATE -> Projects/leads_master.xlsx -> Resend.

Leads land in the ONE master workbook shared by every repo (master_registry.py).
There is no output/ folder and no per-run CSV: businesses already in the master
are skipped, so re-running never duplicates a lead.

Usage:
  python main.py                 # full run (Apify / Places API / seed_urls.csv)
  python main.py --mock          # built-in demo targets, no API keys needed
  python main.py --limit 25      # cap number of sourced targets
  python main.py --no-email      # build the CSV but skip Resend delivery
  python main.py --category 3    # preselect a business category (skips the menu)
  python main.py --fresh         # ALSO sweep newly-registered NCR domains (<=7d)

At startup a numbered menu of BUSINESS_CATEGORIES is shown — enter a number to
source only that category (e.g. 1 = dentist), or press Enter / 0 for all.
"""

import argparse
import os
import sys

import config
import master_registry
from contact_scraper import scrape_contacts
from delivery import send_master
from fresh_domains import source_fresh_domains
from site_audit import audit_issues
from sitemap_filter import check_last_updated
from target_sourcer import category_bucket, registrable_domain, source_targets


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


def run(mock: bool, limit: int, no_email: bool, fresh: bool = False,
        category: str | None = None) -> int:
    # --- Stage 1: source targets ---
    targets = source_targets(mock=mock, category=category)

    # --- Stage 1b (opt-in): brand-new NCR registrations, found directly ---
    if fresh:
        have = {registrable_domain(t["url"]) for t in targets}
        targets += [t for t in source_fresh_domains()
                    if registrable_domain(t["url"]) not in have]

    # Drop businesses already in the master BEFORE --limit, so the cap fills with
    # fresh leads instead of re-scraping ones we have. Matched on name only: the
    # email and phone that form the strong dedup keys don't exist until stage 3
    # has scraped them, and by then we've already paid for the crawl. upsert()
    # applies the strong keys as the real backstop.
    if not mock:
        known_names = {str(r.get("Business Name") or "").strip().lower()
                       for r in master_registry.load_rows()}
        known_names.discard("")
        if known_names:
            before = len(targets)
            targets = [t for t in targets
                       if (t.get("business_name") or "").strip().lower() not in known_names]
            if before - len(targets):
                print(f"[main] {before - len(targets)} businesses already in the "
                      "master file — skipped")

    if limit > 0:
        targets = targets[:limit]
    if not targets:
        print("[main] no targets sourced — nothing to do")
        return 1

    rows: list[dict] = []
    stats = {"sourced": len(targets), "update_rejected": 0, "no_contact": 0, "kept": 0}

    for i, target in enumerate(targets, 1):
        url = target["url"]
        domain = registrable_domain(url)
        print(f"\n[main] ({i}/{len(targets)}) {target['business_name']} — {domain}")

        # --- Stage 2: sitemap last-updated gate (skipped for fresh-sweep
        # targets, which are <=7 days old by construction from the dated
        # NRD list and rarely publish a sitemap yet) ---
        updated_label = target.get("update_label") or check_last_updated(url, domain)
        if updated_label is None:
            stats["update_rejected"] += 1
            continue

        # --- Stage 3: contact extraction ---
        contacts = scrape_contacts(url)

        # --- Stage 4: STRICT VALIDATION GATE ---
        # Rule: if email IS NULL and phone IS NULL, discard the row entirely.
        if not contacts["email"] and not contacts["phone"]:
            print(f"[main] {domain}: no email AND no phone — row discarded")
            stats["no_contact"] += 1
            continue

        stats["kept"] += 1
        print(f"[main] {domain}: KEPT (email={contacts['email']}, phone={contacts['phone']})")
        issues = audit_issues(contacts.get("home_html"), url, updated_label)
        rows.append({
            "Business Name": target["business_name"],
            "Category": category_bucket(target, category),
            "Lead Type": master_registry.LEAD_TYPE_STALE_SITE,
            "Has_Website": True,
            "Phone Number": contacts["phone"] or "",
            "Email Address": contacts["email"] or "",
            "Instagram": "",
            "Rating": "",
            "Reviews": "",
            master_registry.BULLETS_COLUMN:
                master_registry.website_bullets(issues, updated_label),
        })

    # --- Stage 4b: append to the ONE master workbook ---
    # A --mock run must never pollute the real master with fictional businesses.
    # Overriding MASTER_FILE (a scratch path) is the explicit opt-in used by tests.
    if mock and not os.getenv("MASTER_FILE"):
        print("[main] mock run — not touching the real master file")
        added = 0
    else:
        added = master_registry.upsert(rows)

    print(
        f"\n[main] done: sourced={stats['sourced']} "
        f"update_rejected={stats['update_rejected']} no_contact={stats['no_contact']} "
        f"kept={stats['kept']} added={added}"
    )
    print(f"[main] master -> {master_registry.MASTER_FILE}")
    if stats["kept"] - added:
        print(f"[main] {stats['kept'] - added} were already in the master file")

    # --- Stage 5: delivery (wa1.txt theory) ---
    if no_email:
        print("[main] --no-email set — skipping delivery")
    elif not added:
        print("[main] 0 new leads — skipping delivery")
    else:
        send_master(added)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delhi NCR business leads pipeline")
    parser.add_argument("--mock", action="store_true", help="use built-in demo targets")
    parser.add_argument("--limit", type=int, default=0, help="cap sourced targets")
    parser.add_argument("--no-email", action="store_true", help="skip Resend delivery")
    parser.add_argument("--category", type=int, default=None,
                        help="business category number (1-based, see startup menu); "
                             "omit for the interactive menu, 0 for all")
    parser.add_argument("--fresh", action="store_true",
                        help="also sweep newly-registered NCR domains (<=7 days old)")
    args = parser.parse_args()
    chosen = pick_category(args.category)
    sys.exit(run(mock=args.mock, limit=args.limit, no_email=args.no_email,
                 fresh=args.fresh, category=chosen))
