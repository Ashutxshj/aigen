"""Newly-registered domains that have NOT launched a site yet.

The generic "is this domain parked?" check that /scraper/fresh_domains.py does
mostly finds squatters — people who buy domains to resell, who will never hire a
designer. Two much sharper signals replace it:

  * A Shopify/Wix/Squarespace PLACEHOLDER. Somebody paid for a store builder,
    started, and has not launched. Their card is already out and they are stuck.
    This is the strongest structural signal available anywhere in this repo.

  * MX RECORDS BUT NO WEBSITE. They set up business email — hello@theirshop.com
    resolves — and there is no site behind it. That is a real business, funded
    enough to buy a domain and mail hosting, with nothing to show a customer.

Both are inferences: nobody asked us for anything. They are tagged
signal_type="structural" and can never be presented as if the person requested
help. Pitching a structural lead like an explicit ask is how you sound like spam.

WHOIS itself is useless here post-GDPR: registrant contact is redacted. So this
collector produces a DOMAIN, not a person. The contact has to come from the site
or from a directory cross-reference.
"""

import io
import re
import socket
import zipfile
from datetime import datetime, timedelta

import config
from collectors.base import Collector
from core import log
from core.models import Signal, utcnow

logger = log.get("newdomains")

# Fingerprints of "paid for a builder, never launched".
PLACEHOLDER_MARKERS = [
    ("shopify", ["shopify.shop", "/password", "this store will be available"]),
    ("wix", ["wix.com", "coming soon", "this site is under construction"]),
    ("squarespace", ["squarespace", "website coming soon"]),
    ("carrd", ["carrd.co"]),
    ("godaddy", ["godaddy", "future home of", "domain is parked"]),
    ("generic", ["under construction", "coming soon", "launching soon"]),
]


def _has_mx(domain: str) -> bool:
    """True if the domain accepts mail. Cheap proxy for 'a real business'.

    Uses dnspython if present; if it is not installed we return False rather than
    guessing True — a false 'has email' would invent a fact we then can't back up.
    """
    try:
        import dns.resolver
    except ImportError:
        return False
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        return False


def _resolves(domain: str) -> bool:
    try:
        socket.gethostbyname(domain)
        return True
    except OSError:
        return False


class NewDomainsCollector(Collector):
    name = "newdomains"
    bucket = "newdomains"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def _feed(self, day: datetime) -> list[str]:
        """WhoisDS publishes one zip of the previous day's registrations."""
        key = day.strftime("%Y-%m-%d")
        url = config.WHOISDS_URL.format(key=key)
        resp = self.scraper.get(url, self.bucket)
        if resp is None or resp.status_code != 200:
            logger.warning("newdomains: feed unavailable for %s", key)
            return []
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                name = zf.namelist()[0]
                return zf.read(name).decode("utf-8", "replace").split()
        except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
            logger.warning("newdomains: bad zip for %s: %s", key, exc)
            return []

    def _classify(self, domain: str) -> tuple[str, str] | None:
        """(builder, evidence) if this domain looks like an unlaunched business."""
        url = f"http://{domain}"
        resp = self.scraper.get(url, "web", allow_redirects=True)
        if resp is None:
            # Nothing served at all. If it has MX, somebody set up business
            # email and never built a site — that is the cleaner half of the
            # signal, and it needs no HTML.
            if _has_mx(domain):
                return "mx_no_site", "domain accepts email but serves no website"
            return None

        html = (resp.text or "")[:20000].lower()
        if len(html) > 8000:
            return None                     # a real site, not a placeholder

        for builder, markers in PLACEHOLDER_MARKERS:
            for marker in markers:
                if marker in html:
                    return builder, f"placeholder page ({builder})"
        return None

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("newdomains") or {}
            return [Signal(
                source_uid=f"nrd:{d['domain']}",
                platform="newdomains",
                source_detail=d.get("builder", "mock"),
                permalink=f"http://{d['domain']}",
                post_title=d["domain"],
                body=d.get("evidence", ""),
                posted_at=utcnow() - timedelta(hours=6),
                signal_type="structural",
                website=f"http://{d['domain']}",
                contact_channel="form",
            ) for d in raw.get("domains", [])]

        out: list[Signal] = []
        probed = 0
        for back in range(1, config.NRD_DAYS_BACK + 1):
            day = utcnow() - timedelta(days=back)
            domains = self._feed(day)
            if not domains:
                continue
            # The feed is millions of domains. Only probe ones whose NAME looks
            # like a small business we could actually sell to — probing all of
            # them would take days and get us rate-limited everywhere.
            candidates = [d for d in domains
                          if any(k in d.lower() for k in config.NRD_KEYWORDS)]
            logger.info("newdomains: %d/%d candidates for %s",
                        len(candidates), len(domains), day.date())

            for domain in candidates:
                if probed >= config.NRD_MAX_PROBES:
                    logger.warning("newdomains: hit NRD_MAX_PROBES (%d) — "
                                   "stopping early, %d candidates unprobed",
                                   config.NRD_MAX_PROBES,
                                   len(candidates) - probed)
                    return out
                probed += 1
                verdict = self._classify(domain)
                if not verdict:
                    continue
                builder, evidence = verdict
                out.append(Signal(
                    source_uid=f"nrd:{domain}",
                    platform="newdomains",
                    source_detail=builder,
                    permalink=f"http://{domain}",
                    post_title=domain,
                    body=(f"Domain registered on {day.date()}. {evidence}. "
                          "No live website."),
                    posted_at=day,
                    signal_type="structural",
                    website=f"http://{domain}",
                    contact_channel="form",
                ))
        return out
