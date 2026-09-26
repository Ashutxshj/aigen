"""When was this domain registered? RDAP first, classic WHOIS as fallback.

RDAP (the registries' JSON successor to WHOIS) is free, needs no key, and
https://rdap.org/domain/<domain> bootstraps to the right registry for any TLD.
If RDAP has no answer, a raw port-43 WHOIS query against the registry servers
for the common US TLDs is tried before giving up.

Every answer — including "couldn't find out" — is cached in age_cache.json so
a domain is never looked up twice across runs. Lookups cost nothing but the
registries do throttle; WHOIS_DELAY_SECONDS paces the loop in main.py.
"""

import json
import os
import re
import socket
from datetime import date, datetime

import requests

import config

RDAP_URL = "https://rdap.org/domain/{domain}"

# Registry WHOIS servers for the TLDs a US small business actually uses.
_WHOIS_SERVERS = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.publicinterestregistry.org",
    "info": "whois.nic.info",
    "biz": "whois.nic.biz",
    "us": "whois.nic.us",
}

_CREATED_RE = re.compile(
    r"(?:Creation Date|Created On|created|Registration Date|Registered On)"
    r"\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)

# Deterministic dates for --mock runs, keyed by the mock targets' domains.
_MOCK_DATES = {
    "hendrickslaw-al.com": "2003-06-14",
    "riversidefamilydental.com": "2009-02-27",
    "tricountyplumbingal.com": "2001-11-05",
    "mcdonalds.com": "1994-05-06",
    "glowbeautysalon.com": "2004-01-01",
}


# --- cache -------------------------------------------------------------------

def load_cache() -> dict:
    if not os.path.exists(config.AGE_CACHE_FILE):
        return {}
    try:
        with open(config.AGE_CACHE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        print("[whois] age_cache.json unreadable — starting a fresh cache")
        return {}


def save_cache(cache: dict) -> None:
    with open(config.AGE_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)


# --- lookups -----------------------------------------------------------------

def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _from_rdap(domain: str):
    try:
        resp = requests.get(
            RDAP_URL.format(domain=domain),
            timeout=config.REQUEST_TIMEOUT,
            headers={"Accept": "application/rdap+json",
                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) murica/1.0"},
        )
    except requests.RequestException as exc:
        print(f"[whois] RDAP unreachable for {domain}: {type(exc).__name__}")
        return None
    if resp.status_code != 200:
        return None
    try:
        events = resp.json().get("events", [])
    except ValueError:
        return None
    for ev in events:
        if ev.get("eventAction") == "registration" and ev.get("eventDate"):
            return _parse_iso(str(ev["eventDate"]))
    return None


def _from_whois43(domain: str):
    server = _WHOIS_SERVERS.get(domain.rsplit(".", 1)[-1])
    if not server:
        return None
    try:
        with socket.create_connection((server, 43), timeout=config.REQUEST_TIMEOUT) as sock:
            sock.sendall((domain + "\r\n").encode("ascii", "ignore"))
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
    except OSError as exc:
        print(f"[whois] WHOIS {server} unreachable for {domain}: {type(exc).__name__}")
        return None
    m = _CREATED_RE.search(b"".join(chunks).decode("utf-8", "replace"))
    return _parse_iso(m.group(1)) if m else None


def registration_date(domain: str, cache: dict, mock: bool = False):
    """date the domain was registered, or None if no registry would say.
    Consults/updates `cache` (persist it with save_cache once per run)."""
    if mock:
        value = _MOCK_DATES.get(domain, "")
        return _parse_iso(value) if value else None

    if domain in cache:
        value = cache[domain].get("registered", "")
        return _parse_iso(value) if value else None

    registered = _from_rdap(domain) or _from_whois43(domain)
    cache[domain] = {"registered": registered.isoformat() if registered else "",
                     "at": date.today().isoformat()}
    return registered


def age_years(registered: date) -> float:
    return (date.today() - registered).days / 365.25
