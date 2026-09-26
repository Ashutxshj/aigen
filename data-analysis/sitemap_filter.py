"""Stage 2 — Site FRESHNESS via the website's own sitemap.xml <lastmod>.

The question is no longer "when was this domain created" but "when was this
website last UPDATED". The most recent <lastmod> across a site's sitemap is
taken as its last-update date.

STALE-ONLY rule: keep a site ONLY if it was last updated >= MIN_STALE_DAYS
ago (neglected site — prime redesign lead). Recently-updated sites, and sites
with no discoverable sitemap / no <lastmod> dates, are discarded. (Brand-new
sites enter the pipeline only via the opt-in --fresh sweep, which bypasses
this gate.)

Sitemap discovery order:
  1. robots.txt "Sitemap:" directives
  2. Common fallback paths: /sitemap.xml, /sitemap_index.xml,
     /sitemap-index.xml, /wp-sitemap.xml
A sitemap index is followed one level down; if the index entries carry no
<lastmod> themselves, up to SITEMAP_MAX_CHILDREN child sitemaps are fetched.
"""

import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin

import config
import http_client

FALLBACK_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
]


def _local_tag(element) -> str:
    """Tag name without its XML namespace ('{ns}urlset' -> 'urlset')."""
    return element.tag.rsplit("}", 1)[-1].lower()


def _parse_lastmod(text: str | None) -> datetime | None:
    """Parse a <lastmod> value: date-only or full ISO 8601 (Z or offset)."""
    if not text:
        return None
    text = text.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fetch_xml(url: str) -> ET.Element | None:
    resp = http_client.get(url, timeout=25)
    if resp is None or resp.status_code != 200:
        return None
    content = resp.content
    if content[:2] == b"\x1f\x8b":  # gzipped sitemap (.xml.gz)
        try:
            content = gzip.decompress(content)
        except OSError:
            return None
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        return None


def _sitemaps_from_robots(base: str) -> list[str]:
    resp = http_client.get(urljoin(base, "/robots.txt"), timeout=15)
    if resp is None or resp.status_code != 200:
        return []
    found = []
    for line in resp.text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            found.append(value.strip())
    return found


def _latest_lastmod(root: ET.Element, follow_children: bool) -> datetime | None:
    """Most recent <lastmod> in a urlset, or across a sitemap index."""
    tag = _local_tag(root)

    if tag == "urlset":
        dates = [d for entry in root
                 for child in entry if _local_tag(child) == "lastmod"
                 for d in [_parse_lastmod(child.text)] if d]
        return max(dates, default=None)

    if tag == "sitemapindex":
        entries = []  # (loc, lastmod|None) per child sitemap
        for entry in root:
            loc, lastmod = None, None
            for child in entry:
                if _local_tag(child) == "loc":
                    loc = (child.text or "").strip()
                elif _local_tag(child) == "lastmod":
                    lastmod = _parse_lastmod(child.text)
            if loc or lastmod:
                entries.append((loc, lastmod))

        # Index-level <lastmod> stamps are the cheap answer when present.
        stamped = [lm for _, lm in entries if lm]
        if stamped:
            return max(stamped)

        if not follow_children:
            return None
        dates = []
        for loc, _ in entries[: config.SITEMAP_MAX_CHILDREN]:
            if not loc:
                continue
            child_root = _fetch_xml(loc)
            if child_root is not None:
                d = _latest_lastmod(child_root, follow_children=False)
                if d:
                    dates.append(d)
        return max(dates, default=None)

    return None


def _find_last_updated(site_url: str) -> datetime | None:
    base = site_url if site_url.startswith("http") else f"https://{site_url}"
    candidates = _sitemaps_from_robots(base)
    candidates += [urljoin(base, p) for p in FALLBACK_SITEMAP_PATHS
                   if urljoin(base, p) not in candidates]
    for sitemap_url in candidates:
        root = _fetch_xml(sitemap_url)
        if root is None:
            continue
        last = _latest_lastmod(root, follow_children=True)
        if last:
            print(f"[sitemap] using {sitemap_url}")
            return last
    return None


def check_last_updated(site_url: str, domain: str) -> str | None:
    """Return a 'Last Updated' label if the site passes the freshness filter,
    else None (discard). Label always leads with the ISO date for the CSV."""
    last = _find_last_updated(site_url)
    if last is None:
        print(f"[sitemap] {domain}: no sitemap/<lastmod> found — discarded")
        return None

    days = max(0, (datetime.now(timezone.utc) - last).days)
    if days >= config.MIN_STALE_DAYS:
        label = f"{last:%Y-%m-%d} ({days} days ago — stale)"
        print(f"[sitemap] {domain}: last updated {label} — kept (1+ year untouched)")
        return label
    print(f"[sitemap] {domain}: last updated {last:%Y-%m-%d} ({days} days ago) — "
          f"updated too recently, discarded")
    return None
