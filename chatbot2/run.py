"""leeds-hour — one command: the last hour's leads, in your inbox.

    python run.py

Runs the sibling `leeds` pipeline with a ONE HOUR window over the fast sources
only, writes hour_leads.xlsx HERE (never leeds' sheet, never leads_master),
and emails it to you via Resend. Then it exits — there is no loop, no daemon,
no schedule. You run it when you want leads.

Everything heavy is imported from ../leeds — this repo adds a window, a
platform list and a mailer, nothing else. Every improvement to leeds' scoring,
drafting and safety rules applies here automatically.
"""

import argparse
import os
import sys
from datetime import timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
LEEDS = os.path.normpath(os.path.join(BASE, "..", "leeds"))
if not os.path.isdir(LEEDS):
    sys.exit(f"cannot find the leeds repo at {LEEDS} — leeds-hour reuses its "
             "code and must live next to it")


def _load_env(path: str) -> None:
    """BASE/.env into the environment; real env vars win. Hand-rolled so
    python-dotenv stays a non-dependency (same trick as leeds/config.py)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(),
                                  value.strip().strip('"').strip("'"))


_load_env(os.path.join(BASE, ".env"))

# THE LOAD-BEARING LINES. leeds' config reads these at import time, so they
# must be set BEFORE the import below — this is what points every stage at
# THIS repo's working store and sheet instead of leeds' own.
os.environ["LEEDS_DB"] = os.path.join(BASE, "leads.db")
os.environ["INTENT_FILE"] = os.path.join(BASE, "hour_leads.xlsx")

sys.path.insert(0, LEEDS)

import config                                     # noqa: E402  (leeds' config)
import main as leeds                              # noqa: E402
from core.models import utcnow                    # noqa: E402
from export import excel                          # noqa: E402

import mailer                                     # noqa: E402  (ours)

# The sources that can possibly have something NEW in a one-hour window.
# directories (OSM), newdomains and registries move on a timescale of days and
# each Overpass city costs ~2 minutes — running them hourly is pure waste.
FAST_PLATFORMS = ["reddit", "forums", "stackexchange", "bluesky",
                  "hackernews", "jobboards"]

WINDOW_HOURS = 1


def run(min_score: int, send_email: bool, verbose: bool) -> int:
    ctx = leeds.Ctx(mock=False, dry_run=False, mock_llm=False, verbose=verbose)

    for platform in FAST_PLATFORMS:
        leeds.do_collect(ctx, WINDOW_HOURS, platform)
    leeds.do_score(ctx, WINDOW_HOURS, "")
    leeds.do_enrich(ctx, WINDOW_HOURS, min_score)
    leeds.do_draft(ctx, WINDOW_HOURS, min_score)
    path = leeds.do_export(ctx, WINDOW_HOURS, min_score)

    since = utcnow() - timedelta(hours=WINDOW_HOURS)
    hour_leads = excel.exportable(ctx.store.leads(since, min_score=min_score))

    print(f"\n  {len(hour_leads)} lead(s) in the last hour  (sheet: {path})")

    if not send_email:
        print("  --no-email: not sending anything")
        return 0

    ok = mailer.send_sheet(path, hour_leads)
    if not ok:
        # The sheet exists and is correct; only delivery failed. Say so and
        # exit non-zero — a silent delivery failure would look like a quiet
        # hour, which is the one lie this pipeline is not allowed to tell.
        print("  EMAIL FAILED — the sheet was still written, open it directly")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-score", type=int, default=config.MIN_SCORE_DEFAULT,
                    help=f"floor for the sheet/email "
                         f"(default {config.MIN_SCORE_DEFAULT})")
    ap.add_argument("--no-email", action="store_true",
                    help="write the sheet but send nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args.min_score, not args.no_email, args.verbose))
