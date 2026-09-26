"""Niche: pick ONE business niche -> Google Maps businesses with NO website ->
one-line pitch each -> styled XLSX -> emailed to you via Resend.

Nothing here contacts a lead: the single outbound email goes to YOUR inbox with
the sheet attached; the Message column is what you send by hand.

seen.json remembers every business ever put in a sheet, so re-running a niche
only ever emails you NEW leads.

Usage:
  python main.py --niche restaurants          # scrape, sheet, email
  python main.py --niche restaurants --no-email --out path.xlsx
  python main.py --list-niches                # one niche per line (for UIs)
  python main.py --niche restaurants --mock   # demo targets, no API keys
  python main.py --niche restaurants --fresh  # ignore seen.json this run
"""

import argparse
import json
import os
import sys
from datetime import datetime

import config
import mailer
import pitch
import sheet
from sourcer import source_targets


# --- seen registry -----------------------------------------------------------

def _key(t: dict) -> str:
    return (t.get("place_id")
            or f"{t.get('business_name', '').lower()}|{t.get('address', '').lower()}")


def _load_seen() -> dict:
    if not os.path.exists(config.SEEN_FILE):
        return {}
    try:
        with open(config.SEEN_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        print("[niche] seen.json unreadable — starting a fresh registry")
        return {}


def _save_seen(seen: dict) -> None:
    with open(config.SEEN_FILE, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, ensure_ascii=False, indent=1)


# --- pipeline ----------------------------------------------------------------

def run(niche: str, out_path: str, no_email: bool, mock: bool, fresh: bool) -> int:
    print(f"[niche] === {niche} ===")
    targets = source_targets(niche, mock=mock)

    seen = _load_seen()
    if fresh:
        print("[niche] --fresh: skipping the seen.json filter this run")
        new = targets
    else:
        new = [t for t in targets if _key(t) not in seen]
        if len(new) != len(targets):
            print(f"[niche] {len(targets) - len(new)} already sent before — skipped")
    if not new:
        print("[niche] 0 new leads — nothing to sheet or send")
        return 0

    leads = [(t, pitch.one_liner(t, niche)) for t in new]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.write(out_path, leads)
    print(f"[niche] wrote {len(leads)} lead(s) -> {out_path}")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for t in new:
        seen[_key(t)] = {"niche": niche, "name": t.get("business_name", ""),
                         "at": stamp}
    _save_seen(seen)

    if no_email:
        print("[niche] --no-email: skipping Resend delivery")
        return 0

    subject = f"Niche leads, {niche}: {len(leads)} new"
    body = (
        f"<p><b>{len(leads)}</b> new <b>{niche}</b> business(es) with no website, "
        f"each with a ready one-line pitch in the Message column.</p>"
        f"<p>Sorted easiest-to-reach first; the WhatsApp column links straight "
        f"to a chat. Open the sheet, copy the Message, send by hand.</p>"
    )
    ok, _, detail = mailer.send(out_path, subject, body)
    print(f"[niche] mail: {detail}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--niche", help="one of config.NICHES (or any Maps search term)")
    ap.add_argument("--list-niches", action="store_true",
                    help="print the dropdown list, one per line, and exit")
    ap.add_argument("--out", help="xlsx output path (default: out/<niche>_<stamp>.xlsx)")
    ap.add_argument("--no-email", action="store_true", help="build the sheet, skip Resend")
    ap.add_argument("--mock", action="store_true", help="built-in demo targets, no keys")
    ap.add_argument("--fresh", action="store_true", help="ignore seen.json this run")
    args = ap.parse_args()

    if args.list_niches:
        print("\n".join(config.NICHES))
        return 0
    if not args.niche:
        ap.error("--niche is required (or use --list-niches)")

    niche = args.niche.strip().lower()
    if niche not in config.NICHES:
        print(f"[niche] '{niche}' is not in config.NICHES — searching it anyway")

    out_path = args.out
    if not out_path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = niche.replace(" ", "_")
        out_path = os.path.join(config.OUT_DIR, f"{slug}_{stamp}.xlsx")

    return run(niche, out_path, args.no_email, args.mock, args.fresh)


if __name__ == "__main__":
    sys.exit(main())
