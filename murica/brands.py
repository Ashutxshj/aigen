"""The famous-brand blocklist: is this business a well-known MNC/chain?

famous_brands.csv holds one famous name per line (header: name). A target is
famous when a blocklisted name appears as whole words inside its business name,
or (for names long enough to be unambiguous) collapsed inside its domain —
"mcdonalds" in mcdonalds-tulsa.com is a franchise, not a lead.

Over-excluding is the correct failure mode here: a false positive costs one
lead slot, a false negative emails you a Fortune 500 company as a "prospect".
"""

import csv
import os
import re

import config

_WORD_RE = re.compile(r"[^a-z0-9]+")

# Below this collapsed length, a name is too generic to match inside a domain
# ("gap" would hit gaplawfirm.com; "ram" would hit ramplumbing.com).
_MIN_DOMAIN_MATCH_LEN = 6


def _normalize(text: str) -> str:
    """Lowercase, apostrophes removed, everything else non-alnum -> space.
    "McDonald's" -> "mcdonalds"; "H&R Block" -> "h r block"."""
    text = text.lower().replace("'", "").replace("’", "")
    return _WORD_RE.sub(" ", text).strip()


def load() -> list:
    """[(normalized_name, collapsed_name), ...] from famous_brands.csv."""
    if not os.path.exists(config.FAMOUS_FILE):
        print(f"[brands] {os.path.basename(config.FAMOUS_FILE)} missing — "
              f"famous-brand filter disabled")
        return []
    out = []
    with open(config.FAMOUS_FILE, "r", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            norm = _normalize(row.get("name") or "")
            if norm:
                out.append((norm, norm.replace(" ", "")))
    return out


def match(brands: list, business_name: str, domain: str):
    """The blocklisted name this target trips on, or None if it is clean."""
    name_hay = f" {_normalize(business_name)} "
    domain_hay = _WORD_RE.sub("", (domain or "").lower())
    for norm, collapsed in brands:
        if f" {norm} " in name_hay:
            return norm
        if len(collapsed) >= _MIN_DOMAIN_MATCH_LEN and collapsed in domain_hay:
            return norm
    return None
