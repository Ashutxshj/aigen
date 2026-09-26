"""Murica: pick ONE US state -> Google Maps businesses with their OWN website ->
WHOIS the domain -> keep only decade-old sites -> famous brands filtered out ->
one-line pitch each -> styled XLSX -> emailed to you via Resend.

Nothing here contacts a lead: the single outbound email goes to YOUR inbox with
the sheet attached; the Message column is what you send by hand.

seen.json remembers every business ever put in a sheet, so re-running a state
only ever emails you NEW leads. age_cache.json remembers every WHOIS answer so
a domain is never looked up twice. progress.json rotates the search categories
per state so repeat runs spend Apify credits on new ground.

Usage:
  python main.py --state Alabama              # scrape, whois, sheet, email
  python main.py --state Alabama --no-email --out path.xlsx
  python main.py --list-states                # one state per line (for UIs)
  python main.py --state Alabama --mock       # demo targets, no API keys
  python main.py --state Alabama --fresh      # ignore seen.json this run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import config
import mailer
import pitch
import sheet
import whoisage
from sourcer import source_targets


# --- seen registry -----------------------------------------------------------

def _key(t: dict) -> str:
    return (t.get("domain")
            or t.get("place_id")
            or f"{t.get('business_name', '').lower()}|{t.get('address', '').lower()}")


def _load_seen() -> dict:
    if not os.path.exists(config.SEEN_FILE):
        return {}
    try:
        with open(config.SEEN_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        print("[murica] seen.json unreadable — starting a fresh registry")
        return {}


def _save_seen(seen: dict) -> None:
    with open(config.SEEN_FILE, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=1)


# --- pipeline ----------------------------------------------------------------

def run(state: str, out_path: str, no_email: bool, mock: bool, fresh: bool) -> int:
    print(f"[murica] === {state} ===")
    targets = source_targets(state, mock=mock)

    seen = _load_seen()
    if fresh:
        print("[murica] --fresh: skipping the seen.json filter this run")
        new = targets
    else:
        new = [t for t in targets if _key(t) not in seen]
        if len(new) != len(targets):
            print(f"[murica] {len(targets) - len(new)} already sent before — skipped")

    # WHOIS gate: walk the candidates until RESULTS_PER_RUN domains prove old
    # enough. Lookups are free (RDAP/WHOIS), cached forever, and politely paced.
    cache = whoisage.load_cache()
    valid, too_young, unknown = [], 0, 0
    for t in new:
        if len(valid) >= config.RESULTS_PER_RUN:
            break
        was_cached = mock or t["domain"] in cache
        registered = whoisage.registration_date(t["domain"], cache, mock=mock)
        if registered is None:
            print(f"[murica] {t['domain']}: no registration date found — skipped")
            unknown += 1
        else:
            age = whoisage.age_years(registered)
            if age >= config.MIN_AGE_YEARS:
                t["registered"] = registered
                t["age"] = age
                valid.append(t)
                print(f"[murica] {t['domain']}: registered {registered.isoformat()} "
                      f"({age:.1f} yrs) — VALID ({len(valid)}/{config.RESULTS_PER_RUN})")
            else:
                print(f"[murica] {t['domain']}: registered {registered.isoformat()} "
                      f"({age:.1f} yrs) — too young")
                too_young += 1
        if not was_cached:
            time.sleep(config.WHOIS_DELAY_SECONDS)
    if not mock:
        whoisage.save_cache(cache)
    print(f"[murica] whois gate: {len(valid)} valid, {too_young} too young, "
          f"{unknown} unknown (min age {config.MIN_AGE_YEARS} yrs)")
    if not valid:
        print("[murica] 0 valid leads — nothing to sheet or send")
        return 0

    leads = [(t, pitch.one_liner(t, t["registered"], t["age"])) for t in valid]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.write(out_path, leads)
    print(f"[murica] wrote {len(leads)} lead(s) -> {out_path}")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for t in valid:
        seen[_key(t)] = {"state": state, "name": t.get("business_name", ""),
                         "registered": t["registered"].isoformat(), "at": stamp}
    _save_seen(seen)

    if no_email:
        print("[murica] --no-email: skipping Resend delivery")
        return 0

    subject = f"Murica leads, {state}: {len(leads)} old-website businesses"
    body = (
        f"<p><b>{len(leads)}</b> {state} business(es) whose own domain is "
        f"<b>{config.MIN_AGE_YEARS}+ years old</b> per WHOIS, each with a ready "
        f"one-line pitch in the Message column.</p>"
        f"<p>Sorted oldest site first; the Website column opens the site so you "
        f"can see the datedness yourself before reaching out. Famous brands and "
        f"businesses that already live off good websites were filtered out.</p>"
        f"<p>Open the sheet, copy the Message, send by hand.</p>"
    )
    ok, _, detail = mailer.send(out_path, subject, body)
    print(f"[murica] mail: {detail}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", help="one of config.STATES (full name, e.g. Texas)")
    ap.add_argument("--list-states", action="store_true",
                    help="print the dropdown list, one per line, and exit")
    ap.add_argument("--out", help="xlsx output path (default: out/<state>_<stamp>.xlsx)")
    ap.add_argument("--no-email", action="store_true", help="build the sheet, skip Resend")
    ap.add_argument("--mock", action="store_true", help="built-in demo targets, no keys")
    ap.add_argument("--fresh", action="store_true", help="ignore seen.json this run")
    args = ap.parse_args()

    if args.list_states:
        print("\n".join(config.STATES))
        return 0
    if not args.state:
        ap.error("--state is required (or use --list-states)")

    state = args.state.strip().title()
    if state not in config.STATES:
        matches = [s for s in config.STATES if s.lower() == args.state.strip().lower()]
        if matches:
            state = matches[0]
        else:
            ap.error(f"'{args.state}' is not a US state — see --list-states")

    out_path = args.out
    if not out_path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = state.lower().replace(" ", "_")
        out_path = os.path.join(config.OUT_DIR, f"{slug}_{stamp}.xlsx")

    return run(state, out_path, args.no_email, args.mock, args.fresh)


if __name__ == "__main__":
    sys.exit(main())
