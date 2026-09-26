"""Stage 5 — report delivery TO THE OPERATOR, per the wa1.txt theory:

  build artifact -> base64 attach -> one transactional Resend send -> log send

Attaches the ONE master workbook (Projects/leads_master.xlsx). This is the only
legitimate use of Resend in the project: it mails YOU the leads. Resend's AUP
prohibits cold outreach to scraped lists, so prospect messages never go through
here — /email-automation drafts them for manual sending and has no send path.

Traits:
  * No marketing body: the subject line is repeated as the plain `text`.
  * Subject carries the payload count.
  * The send is logged best-effort AFTER a successful delivery.
  * Delivery failure is logged, never fatal — the master always survives on disk.
"""

import base64
import json
import os
from datetime import datetime, timezone

import config
import master_registry


def _log_send(record: dict) -> None:
    """Best-effort JSONL append — the report_sends analog. Never raises."""
    try:
        os.makedirs(os.path.dirname(config.SENDS_LOG_FILE) or ".", exist_ok=True)
        with open(config.SENDS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"[delivery] WARN: could not write send log: {exc}")


def send_master(new_leads: int) -> bool:
    """Email the master workbook as a base64 attachment. True on success."""
    path = master_registry.MASTER_FILE
    if not config.RESEND_API_KEY or not config.RECIPIENT_EMAIL:
        print("[delivery] RESEND_API_KEY/RECIPIENT_EMAIL not set — skipping email "
              f"(master is on disk at {path})")
        return False
    if not os.path.exists(path):
        print(f"[delivery] no master workbook at {path} — nothing to send")
        return False

    import resend
    resend.api_key = config.RESEND_API_KEY

    with open(path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    filename = os.path.basename(path)
    total = len(master_registry.load_rows())
    subject = (f"Delhi NCR leads: {new_leads} new "
               f"(master now holds {total})")

    print(f"[delivery] sending {filename} ({new_leads} new) to {config.RECIPIENT_EMAIL}")
    try:
        result = resend.Emails.send({
            "from": config.RESEND_FROM_EMAIL,
            "to": [config.RECIPIENT_EMAIL],
            "subject": subject,
            "text": subject,  # no HTML body — the value IS the attachment
            "attachments": [{"filename": filename, "content": content_b64}],
        })
    except Exception as exc:
        print(f"[delivery] ERROR: Resend send failed: {exc}")
        print(f"[delivery] master preserved at {path}")
        return False

    send_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    print(f"[delivery] email sent to {config.RECIPIENT_EMAIL} (resend id: {send_id})")
    _log_send({
        "to": config.RECIPIENT_EMAIL.lower(),
        "filename": filename,
        "newLeads": new_leads,
        "totalLeads": total,
        "resendId": send_id,
        "sentAt": datetime.now(timezone.utc).isoformat(),
    })
    return True
