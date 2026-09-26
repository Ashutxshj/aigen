"""Stage 3b — Website issue audit: one-line description of what's visibly
wrong with a lead's website, for the CSV's "Website Issues" column.

Heuristics run on the homepage HTML already fetched by contact_scraper (no
extra requests): mobile-viewport tag, HTTPS, stale footer copyright year,
obsolete HTML tags / Flash / ancient jQuery, missing SEO basics. The sitemap
staleness (days since last update) leads the description, parsed from the
"Last Updated" label main.py already has.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

_DAYS_RE = re.compile(r"\((\d+) days? ago")
_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\D{0,20}?((?:19|20)\d{2})", re.IGNORECASE)
_OLD_JQUERY_RE = re.compile(r"jquery[/.-]1\.\d", re.IGNORECASE)


def _stale_line(updated_label: str) -> str | None:
    m = _DAYS_RE.search(updated_label or "")
    if not m:
        return None
    days = int(m.group(1))
    if days >= 730:
        return f"website content untouched for {days // 365}+ years"
    return f"website content untouched for {days} days"


def audit_issues(html: str | None, url: str, updated_label: str) -> str:
    """Return a one-line, human-readable list of website problems."""
    issues: list[str] = []

    stale = _stale_line(updated_label)
    if stale:
        issues.append(stale)

    if url.lower().startswith("http://"):
        issues.append("no HTTPS (browser flags it 'Not secure')")

    if html is None:
        issues.append("homepage failed to load during scrape")
        return "; ".join(issues) or "site could not be analyzed"

    soup = BeautifulSoup(html, "html.parser")
    lower = html.lower()

    if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        issues.append("no mobile viewport tag — not optimized for phones")

    years = [int(y) for y in _COPYRIGHT_RE.findall(html)]
    if years and max(years) < datetime.now().year - 1:
        issues.append(f"footer copyright stuck at {max(years)}")

    if any(t in lower for t in ("<font", "<marquee", "<center", "bgcolor=")):
        issues.append("uses obsolete 1990s-era HTML tags (outdated design)")

    if ".swf" in lower:
        issues.append("embeds Flash content (dead since 2020)")

    if _OLD_JQUERY_RE.search(html):
        issues.append("runs decade-old jQuery 1.x")

    if not soup.find("meta", attrs={"name": re.compile("^description$", re.I)}):
        issues.append("missing meta description (weak SEO)")

    title = soup.find("title")
    if not title or not title.get_text(strip=True):
        issues.append("missing page title")

    if not issues:
        return "no glaring on-page issues detected"
    if issues == [stale]:
        issues.append("design/markup looks passable but long-neglected")
    return "; ".join(issues)
