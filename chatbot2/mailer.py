"""Email the hour's sheet via Resend. The ONLY thing this repo sends is a
report to YOU — it never contacts a lead, same rule as leeds itself.

Resend free-tier reality, so nobody debugs a mystery later: without a verified
domain you can only send FROM onboarding@resend.dev and TO the email address
that owns the Resend account. RESEND_FROM/RESEND_TO exist for the day a domain
gets verified.
"""

import base64
import html
import os
from datetime import timedelta, timezone, datetime

import requests

import config          # leeds' config — run.py put leeds on sys.path first

RESEND_URL = "https://api.resend.com/emails"

_IST = timezone(timedelta(minutes=config.DISPLAY_UTC_OFFSET_MINUTES),
                config.DISPLAY_TZ_NAME)


def _lead_rows(leads) -> str:
    rows = []
    for lead in leads[:15]:
        s = lead.signal
        title = html.escape((s.post_title or s.body)[:90])
        link = html.escape(s.permalink or "")
        rows.append(
            "<tr>"
            f"<td style='padding:6px 10px'><b>{lead.score}</b></td>"
            f"<td style='padding:6px 10px'>{html.escape(lead.verdict.service_wanted)}</td>"
            f"<td style='padding:6px 10px'>{round(s.age_hours(), 1)}h</td>"
            f"<td style='padding:6px 10px'><a href='{link}'>{title}</a></td>"
            "</tr>")
    return "".join(rows)


def _body(leads) -> str:
    now = datetime.now(tz=_IST).strftime("%Y-%m-%d %H:%M")
    if not leads:
        return (f"<p>Ran at <b>{now} {config.DISPLAY_TZ_NAME}</b>. "
                "<b>No leads in the last hour.</b> Quiet hours are normal — "
                "the sources simply had nothing new.</p>")
    return (
        f"<p>Ran at <b>{now} {config.DISPLAY_TZ_NAME}</b> — "
        f"<b>{len(leads)} lead(s) in the last hour.</b> "
        "Full detail (openers, contacts, WhatsApp links) is in the attached "
        "sheet.</p>"
        "<table style='border-collapse:collapse;font:14px sans-serif'>"
        "<tr><th style='text-align:left;padding:6px 10px'>Score</th>"
        "<th style='text-align:left;padding:6px 10px'>Wants</th>"
        "<th style='text-align:left;padding:6px 10px'>Age</th>"
        "<th style='text-align:left;padding:6px 10px'>Post</th></tr>"
        f"{_lead_rows(leads)}</table>"
        "<p style='color:#777'>Speed is the whole edge — a lead older than a "
        "few hours has already collected its replies.</p>")


def send_sheet(sheet_path: str, leads) -> bool:
    key = os.getenv("RESEND_API_KEY", "").strip()
    if not key:
        print("  RESEND_API_KEY is not set (put it in leeds-hour/.env)")
        return False

    with open(sheet_path, "rb") as fh:
        content = base64.b64encode(fh.read()).decode("ascii")

    payload = {
        "from": os.getenv("RESEND_FROM", "leeds-hour <onboarding@resend.dev>"),
        "to": [os.getenv("RESEND_TO", "info.chillispark@gmail.com")],
        "subject": f"leeds-hour: {len(leads)} lead(s) in the last hour",
        "html": _body(leads),
        "attachments": [{"filename": os.path.basename(sheet_path),
                         "content": content}],
    }
    resp = requests.post(RESEND_URL, json=payload, timeout=30,
                         headers={"Authorization": f"Bearer {key}"})
    if resp.status_code != 200:
        print(f"  Resend refused the send: HTTP {resp.status_code} — "
              f"{resp.text[:300]}")
        return False
    print(f"  emailed {payload['to'][0]} (id {resp.json().get('id', '?')})")
    return True
