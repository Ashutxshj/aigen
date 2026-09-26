"""Write Projects/intent_leads.xlsx.

Two properties matter more than anything else in this file.

1. IT NEVER TOUCHES leads_master.xlsx. That workbook belongs to the other three
   repos and this one has no business in it. There is a test asserting its mtime
   is unchanged after a full run.

2. THE HUMAN'S EDITS SURVIVE. You will open this sheet and type into Status and
   Notes. If export simply rewrote the file from the database, the next run would
   silently erase everything you wrote — and you would not notice until you
   double-messaged somebody. So export READS THE EXISTING SHEET FIRST, merges the
   human-owned columns back into SQLite, and only then rewrites. That order is
   the whole point; do not "simplify" it.

If the file is open in Excel, Windows refuses the write. We do not swallow that:
we write a .new.xlsx alongside and say so loudly, because a silently-skipped
export that reports success is exactly the failure this repo is built to avoid.
"""

import os
import re
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config
from core import log
from core.models import Lead, utcnow
from enrich import contact

logger = log.get("excel")

# The workbook that belongs to the SIBLING repos. This one never writes it.
FORBIDDEN = "leads_master.xlsx"

# The ONE place UTC becomes local time. Everything upstream — the store, the 48h
# window, the age calculation — stays in UTC, because the moment a local time
# leaks into the window logic it shifts the cut by +05:30 and starts silently
# dropping live leads. The sheet is for a human to read, so the sheet, and only
# the sheet, speaks IST.
DISPLAY_TZ = timezone(timedelta(minutes=config.DISPLAY_UTC_OFFSET_MINUTES),
                      config.DISPLAY_TZ_NAME)


def _local(ts: datetime) -> str:
    """An aware-UTC datetime, rendered in the reader's timezone."""
    return ts.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")

# openpyxl refuses to write these (they are not legal in XML) and raises
# IllegalCharacterError — which, uncaught, killed the whole run AFTER collect,
# score, enrich and draft had already done their work. Real post bodies contain
# them (pasted terminal output, form feeds, BELs). Strip, don't crash.
_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CELL_MAX = 32000                       # Excel's hard limit is 32767


def _clean(value):
    if not isinstance(value, str):
        return value
    return _ILLEGAL_RE.sub("", value)[:_CELL_MAX]

# Written by the pipeline. Overwritten on every export.
#
# Deliberately ABSENT, because the human reading this sheet asked for them to
# go: Lead ID (an internal dedup key — rows are identified by Permalink now),
# Posted At / Collected At (Age (hours) says the only thing that matters),
# Geo Method (provenance detail), and the Score (rules)/(LLM) split (the single
# blended Score is the number to sort by; the split still lives in the DB).
MACHINE_COLUMNS = [
    "Platform", "Source", "Permalink", "Username",
    "Username With Platform", "Age (hours)",
    "Country", "Region", "Business Type",
    "Business Stage", "Service Wanted", "Intent Tier", "Signal Type",
    "Score", "Signals Fired",
    "Author Role", "Stated Problem", "Budget Signal", "Post Title",
    "Post Excerpt", "Has Website", "Website", "Phone Number", "WhatsApp",
    "Email Address",
    "Contact Channel", "Other Profiles", "Suggested Opener", "Opener Channel",
    "Draft Status",
]

# Written by YOU, in Excel. The pipeline reads these and never overwrites them.
HUMAN_COLUMNS = ["Status", "Contacted", "Do Not Contact", "Notes"]

COLUMNS = MACHINE_COLUMNS + HUMAN_COLUMNS

WIDE = {"Suggested Opener": 70, "Post Excerpt": 60, "Stated Problem": 40,
        "Signals Fired": 30, "Notes": 30, "Permalink": 45, "Author Context": 40}

_HOT = PatternFill("solid", fgColor="FFF2CC")     # score >= 70


# Row identity in the sheet. Older sheets carried an internal "Lead ID" column;
# it was removed at the user's request, so the Permalink (unique per lead) is
# the key now. Reading still accepts either, or the first re-export after the
# column change would have silently dropped every note the human ever typed.
_KEY_COLUMNS = ("Lead ID", "Permalink")


def _leads_sheet(wb):
    """The sheet whose header row has a row-identity column.

    NOT wb.active. Excel persists whichever tab you last clicked on, so a human
    who reads the Runs tab and saves leaves activeTab=1 in the file — and
    reading THAT sheet finds no key column, looks like "no edits", and every
    Status/Notes cell they ever typed is silently overwritten on the next run.
    Look the sheet up by name, then by header, and never by "whichever tab was
    on top".
    """
    names = ["Leads"] + [n for n in wb.sheetnames if n != "Leads"]
    for name in names:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        row = next(ws.iter_rows(values_only=True), None) or ()
        if any(h in _KEY_COLUMNS for h in row):
            return ws
    return None


def _read_human_edits(path: str) -> tuple[str, dict[str, dict[str, str]]]:
    """(key column, the human's edits keyed by it). ("", {}) if no sheet yet."""
    if not os.path.exists(path):
        return "", {}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        # A corrupt sheet must not silently cost the human their triage notes.
        logger.error("could not read existing %s (%s) — NOT overwriting it. "
                     "Move it aside and re-run.", path, exc)
        raise

    ws = _leads_sheet(wb)
    if ws is None:
        wb.close()
        return "", {}
    rows = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in (next(rows, None) or [])]

    idx = {name: header.index(name) for name in HUMAN_COLUMNS if name in header}
    key = next(k for k in _KEY_COLUMNS if k in header)
    key_at = header.index(key)
    out: dict[str, dict[str, str]] = {}
    for values in rows:
        if not values or key_at >= len(values) or not values[key_at]:
            continue
        uid = str(values[key_at])
        edits = {}
        for name, at in idx.items():
            value = values[at] if at < len(values) else ""
            edits[name.lower().replace(" ", "_")] = (
                "" if value is None else str(value))
        if any(edits.values()):
            out[uid] = edits
    wb.close()
    return key, out


def _row(lead: Lead, human: dict[str, str]) -> list:
    s, v = lead.signal, lead.verdict
    return [_clean(c) for c in [
        s.platform,
        s.source_detail,
        s.permalink,
        s.username,
        s.person_key,
        round(s.age_hours(), 1),
        s.country or v.country,
        s.region or v.region,
        s.business_type or v.business_type,
        v.business_stage,
        v.service_wanted,
        lead.intent_tier,
        s.signal_type,
        lead.score,
        ", ".join(lead.intent_signals)[:300],
        v.role,
        v.stated_problem,
        v.budget_signal,
        s.post_title[:200],
        s.body[:400],
        "yes" if s.website else "no",
        s.website,
        s.phone,
        contact.wa_link(s.phone, s.country or v.country),
        s.email,
        s.contact_channel,
        lead.other_profiles,
        lead.opener,
        lead.opener_channel,
        lead.draft_status,
        human.get("status", ""),
        human.get("contacted", ""),
        human.get("do_not_contact", ""),
        human.get("notes", ""),
    ]]


def exportable(leads: list[Lead]) -> list[Lead]:
    """Rows worth a human's attention: a lead whose Service Wanted is "none"
    is a row the user cannot act on ("wtf am I supposed to pitch?"), so it
    stays in the DB but out of the sheet."""
    return [l for l in leads if l.verdict.service_wanted != "none"]


def export(leads: list[Lead], store, path: str = "") -> str:
    path = path or config.INTENT_FILE

    # Sacred invariant: leads_master.xlsx belongs to the sibling repos. If a
    # stray INTENT_FILE ever points at it, refuse — do not "helpfully" write it.
    if os.path.basename(path).lower() == FORBIDDEN:
        raise RuntimeError(
            f"refusing to write {path}: {FORBIDDEN} belongs to the other repos "
            "and this one must never touch it. Set INTENT_FILE to something else.")

    # 1. Rescue the human's edits BEFORE we touch anything.
    keyed_by, edits = _read_human_edits(path)
    if edits:
        if keyed_by == "Permalink":
            # merge_human_edits wants source_uids; resolve them from the links.
            edits = {uid: vals for link, vals in edits.items()
                     if (uid := store.uid_for_permalink(link))}
        merged = store.merge_human_edits(edits)
        logger.info("merged %d rows of your edits back from the sheet", merged)

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for lead in leads:
        human = store.human_fields(lead.signal.source_uid)
        # A lead you have marked Do Not Contact stays in the sheet (so it does
        # not silently come back next run) but must never be re-surfaced as new.
        ws.append(_row(lead, human))
        row = ws.max_row
        link = lead.signal.permalink
        if link:
            cell = ws.cell(row=row, column=COLUMNS.index("Permalink") + 1)
            cell.hyperlink = link
            cell.style = "Hyperlink"
        wa_cell = ws.cell(row=row, column=COLUMNS.index("WhatsApp") + 1)
        if wa_cell.value:
            wa_cell.hyperlink = wa_cell.value
            wa_cell.style = "Hyperlink"
        if lead.score >= 70:
            ws.cell(row=row, column=COLUMNS.index("Score") + 1).fill = _HOT
        for name in ("Suggested Opener", "Post Excerpt", "Stated Problem"):
            ws.cell(row=row, column=COLUMNS.index(name) + 1).alignment = \
                Alignment(wrap_text=True, vertical="top")

    for i, name in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = \
            WIDE.get(name, min(len(name) + 6, 26))
    ws.freeze_panes = "A2"

    # A second sheet you will want the first time yield drops and you cannot see
    # why: which collector ran, what it fetched, what it kept, what errored.
    runs = wb.create_sheet("Runs")
    runs.append(["Run ID", f"Started At ({config.DISPLAY_TZ_NAME})", "Collector",
                 "Fetched", "Kept", "Gemini Requests", "Errors", "Detail"])
    for cell in runs[1]:
        cell.font = Font(bold=True)
    for r in store.recent_runs(200):
        started = r["started_at"]
        try:
            started = _local(datetime.fromisoformat(str(started)))
        except (TypeError, ValueError):
            pass          # keep the raw string rather than lose the row
        runs.append([r["run_id"], started, r["collector"],
                     r["items_fetched"], r["items_kept"], r["gemini_requests"],
                     r["errors"], r["detail"]])
    for i in range(1, 9):
        runs.column_dimensions[get_column_letter(i)].width = 20

    try:
        wb.save(path)
    except PermissionError:
        # The file is open in Excel. Do NOT pretend this worked.
        fallback = path.replace(".xlsx", ".new.xlsx")
        wb.save(fallback)
        logger.error("%s is open in Excel — could not overwrite it. "
                     "Wrote %s instead. Close Excel and re-run --export.",
                     path, fallback)
        return fallback

    logger.info("wrote %d leads to %s", len(leads), path)
    return path
