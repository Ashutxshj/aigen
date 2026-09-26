"""Business directories — the CONTACTABLE half of the product.

Reddit and HN give you intent without a phone number. Directories give you a
phone number without intent. Neither is a whole lead on its own; enrich/crossref
joins them.

OpenStreetMap Overpass is the primary and the only one on by default:
`nwr[shop][phone][!website]` is, almost literally, "a real business with a phone
and no website". Free, no key, no billing card.

Yelp Fusion is DELIBERATELY ABSENT. It went paid (Starter $7.99/1k calls; plans
from $299/mo), which breaks the no-paid-API rule this repo is built on.

Google Places lost its $200/month free credit in March 2025 and now needs a
billing card on file, so it is opt-in (ENABLE_PLACES / --places), off by default.

JustDial has no API. Scraping it violates their ToS and they block hard. It is
behind ENABLE_JUSTDIAL / --justdial, off by default, and the pipeline must never
DEPEND on it — a source that starts serving CAPTCHAs cannot be load-bearing.
"""

import re
from datetime import datetime, timedelta

import config
from collectors.base import Collector
from core import log
from core.models import Signal, utcnow
from enrich.contact import SOCIAL_HOSTS

logger = log.get("directories")

# nwr = nodes, ways and relations. A shop with a phone and no website.
#
# "No website" has to mean it, not just "no `website` tag": mappers also record
# sites under contact:website and url, and a `brand` (Greggs, Starbucks) is a
# chain whose site definitely exists whether or not anyone tagged it. Every one
# of those slipped through the old query and landed in the sheet as a "lead".
_FILTER = ('[phone][!website][!"contact:website"][!url]'
           '[!brand][!"brand:wikidata"]')
OVERPASS_QUERY = f"""
[out:json][timeout:{{timeout}}];
area[name="{{area}}"]->.a;
(
  nwr[shop]{_FILTER}(area.a);
  nwr[amenity~"^(restaurant|cafe|bar|dentist|clinic)$"]{_FILTER}(area.a);
);
out center {{limit}};
"""

# Tags whose presence means "this business has a web presence we can verify" —
# the query already excludes them, but fixtures and any future query edits go
# through _element too, so the check lives in both places.
_ESTABLISHED_TAGS = ("website", "contact:website", "url", "brand",
                     "brand:wikidata", "wikidata")

# Tags whose VALUE is (or names) a page that might link to the real website.
_LINK_TAGS = ("contact:facebook", "facebook", "contact:instagram", "instagram",
              "contact:twitter", "contact:linkedin")

_OG_URL_RE = re.compile(
    r'property=["\']og:url["\']\s+content=["\'](https?://[^"\']+)', re.I)
_HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)


class DirectoriesCollector(Collector):
    name = "directories"
    bucket = "overpass"

    def __init__(self, *a, areas: list[str] | None = None, **kw):
        super().__init__(*a, **kw)
        # Overpass is ~1 query/10s with a 120s timeout, so each city costs up to
        # two minutes. `--areas "Delhi,Gurugram"` lets you work one market
        # without paying for a sweep of all of them.
        self.areas = areas or config.OVERPASS_AREAS

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("directories") or {}
            return [self._element(e, "mock") for e in raw.get("elements", [])
                    if self._element(e, "mock")]

        logger.info("overpass: sweeping %d areas (%s) — roughly %d min",
                    len(self.areas), ", ".join(self.areas[:4])
                    + ("..." if len(self.areas) > 4 else ""),
                    max(1, len(self.areas) // 4))

        out: list[Signal] = []
        for area in self.areas:
            query = OVERPASS_QUERY.format(
                area=area, timeout=config.OVERPASS_TIMEOUT, limit=200)
            resp = self.api.post(config.OVERPASS_URL, self.bucket,
                                 data={"data": query},
                                 timeout=config.OVERPASS_TIMEOUT + 30)
            if resp is None or resp.status_code != 200:
                logger.warning("overpass: no result for %s", area)
                continue
            try:
                payload = resp.json()
            except ValueError:
                logger.warning("overpass: non-JSON for %s", area)
                continue
            found = 0
            for element in payload.get("elements", []):
                sig = self._element(element, area)
                if sig is None:
                    continue
                if self._website_via_links(sig):
                    continue
                out.append(sig)
                found += 1
            logger.info("overpass: %s -> %d businesses with a phone and, as far "
                        "as we can verify, no website", area, found)
        return out

    def _website_via_links(self, sig: Signal) -> str:
        """The website their OSM-listed social links point at, or ''.

        "No website tag" is not "no website" — plenty of businesses have a site
        that only their Facebook page links to. So follow the links the listing
        itself gives us and look for an outbound non-social URL (og:url first:
        that is where a page states its canonical home).

        Best-effort by design: Facebook and Instagram login-wall or robots-block
        most fetches. A BLOCKED fetch is not evidence of a website, so it keeps
        the lead; only a page we actually read and found a site on drops it.
        """
        tags = (sig.raw or {}).get("tags") or {}
        urls = []
        for tag in _LINK_TAGS:
            value = (tags.get(tag) or "").strip()
            if not value:
                continue
            if not value.startswith("http"):
                # OSM allows a bare page name in contact:facebook et al.
                host = tag.split(":")[-1]
                value = f"https://www.{host}.com/{value.lstrip('/')}"
            urls.append(value)

        for url in urls[:2]:                       # cap the cost per business
            resp = self.scraper.get(url, bucket=self.bucket) if self.scraper \
                else None
            if resp is None or resp.status_code != 200:
                continue
            html = resp.text[:200_000]
            for match in _OG_URL_RE.findall(html) + _HREF_RE.findall(html):
                host = match.split("//", 1)[-1].split("/", 1)[0].lower()
                if any(social in host for social in SOCIAL_HOSTS):
                    continue
                logger.debug("drop %s: their %s links to a website (%s)",
                             sig.source_uid, url, match)
                return match
        return ""

    @staticmethod
    def _element(element: dict, area: str) -> Signal | None:
        tags = element.get("tags") or {}
        name = tags.get("name")
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        if not name or not phone:
            return None
        if any(tags.get(t) for t in _ESTABLISHED_TAGS):
            # A website tag under another name, or a chain brand: not a lead.
            return None
        osm_id = f"{element.get('type', 'node')}/{element.get('id')}"
        kind = tags.get("shop") or tags.get("amenity") or "business"

        return Signal(
            source_uid=f"osm:{osm_id}",
            platform="directories",
            source_detail=f"osm:{area}",
            post_title=name,
            body=(f"{name} is a {kind} listed in OpenStreetMap with a phone "
                  f"number and no website tag."),
            # OSM has no "posted" time — this is an observation, made now. Using
            # the element's edit timestamp would be a lie about when the business
            # became a lead.
            posted_at=utcnow() - timedelta(minutes=1),
            signal_type="structural",
            phone=phone,
            email=tags.get("email") or tags.get("contact:email") or "",
            website="",
            region=area,
            country=config.AREA_COUNTRY.get(area, ""),
            business_type=kind,
            contact_channel="phone",
            permalink=f"https://www.openstreetmap.org/{osm_id}",
            raw={"tags": tags},
        )
