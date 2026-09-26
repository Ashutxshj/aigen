"""Classify a business's web presence from whatever URLs its Maps listing exposes.

The whole repo turns on this distinction:

  * real   — the business has an actual website. NOT our lead (that's `/scraper`).
  * social — its only web presence is Instagram/Facebook. Its social page IS its
             website, which makes the handle both the qualifying signal and the
             contact channel. THIS is our lead.
  * none   — no web presence at all. Kept, but reachable only by phone.

A place with a real site *and* an Instagram is `real` — already online, not a
prospect. So "any non-social host wins" is the rule, not "any social host wins".

Callers pass every URL candidate they have; sources disagree about which field
carries the social link, so we classify over the union rather than betting on one.
Never pass the Maps listing URL itself — its host is google.com, which would
classify every place as `real`.
"""

from urllib.parse import urlparse

REAL = "real"
SOCIAL = "social"
NONE = "none"

INSTAGRAM_HOSTS = ("instagram.com", "instagr.am")
FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.me")
SOCIAL_HOSTS = INSTAGRAM_HOSTS + FACEBOOK_HOSTS

# Instagram path segments that are content, not accounts: instagram.com/p/<id>
# is a post, not a handle. Anything here means the URL names no account.
_NON_HANDLE_SEGMENTS = {
    "p", "reel", "reels", "explore", "stories", "tv", "s", "accounts", "direct",
}
# Facebook equivalents: facebook.com/profile.php?id=... carries no vanity handle.
_NON_HANDLE_SEGMENTS |= {"profile.php", "pages", "people", "groups", "events"}


def _host(url: str) -> str:
    """Bare lowercase hostname, no `www.`, no port. '' if unparseable."""
    if not url or not str(url).strip():
        return ""
    raw = str(url).strip()
    if "://" not in raw:
        raw = f"http://{raw}"  # bare 'instagram.com/x' has no scheme to parse
    try:
        host = urlparse(raw).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]  # strip credentials and port
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    """True for the domain itself and any subdomain of it, never for a suffix
    collision like 'notinstagram.com'."""
    return any(host == d or host.endswith(f".{d}") for d in domains)


def is_social(url: str) -> bool:
    return _host_matches(_host(url), SOCIAL_HOSTS)


def classify(*urls: str) -> str:
    """REAL / SOCIAL / NONE over every URL candidate given."""
    hosts = [h for h in (_host(u) for u in urls) if h]
    if not hosts:
        return NONE
    if any(not _host_matches(h, SOCIAL_HOSTS) for h in hosts):
        return REAL
    return SOCIAL


def _handle(url: str, domains: tuple[str, ...]) -> str | None:
    """First path segment of a social URL, if it names an account."""
    if not _host_matches(_host(url), domains):
        return None
    raw = str(url).strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        path = urlparse(raw).path
    except ValueError:
        return None
    segment = path.strip("/").split("/")[0].strip()
    if not segment or segment.lower() in _NON_HANDLE_SEGMENTS:
        return None
    return segment


def instagram_handle(*urls: str) -> str | None:
    """'@handle' from the first Instagram account URL found, else None."""
    for url in urls:
        segment = _handle(url, INSTAGRAM_HOSTS)
        if segment:
            return f"@{segment}"
    return None


def facebook_handle(*urls: str) -> str | None:
    for url in urls:
        segment = _handle(url, FACEBOOK_HOSTS)
        if segment:
            return segment
    return None


def social_url(*urls: str) -> str:
    """The first social URL among the candidates, '' if none."""
    return next((u for u in urls if u and is_social(u)), "")
