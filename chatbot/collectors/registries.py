"""UK Companies House — companies incorporated in the last 48 hours.

Free, official, and nobody works it. A company registered on Tuesday has, by
definition, no website on Wednesday. It is a pure structural signal: they have not
asked for anything, so it is scored as `structural` and must never be pitched as
if they had.

## Getting a key (free, ~2 minutes)

  1. https://developer.company-information.service.gov.uk/ → sign up
  2. Create an application → "Live" environment
  3. Copy the REST API key → COMPANIES_HOUSE_KEY in .env

## Auth is HTTP Basic with the key as the USERNAME and an EMPTY password

That trailing colon in the docs is load-bearing:

    curl -XGET -u YOUR_KEY: https://api.company-information.service.gov.uk/company/00000006
                         ^ empty password

`requests` does this with `auth=(key, "")`. If you pass the key as the password
instead you get a 401 that looks exactly like a bad key.

Rate limit: 600 requests / 5 minutes. They ban for repeated overage, so the bucket
runs well under it.

## What you get, and what you don't

You get: company name, incorporation date, registered office address, SIC codes.
You do NOT get an email or a phone number — Companies House does not publish them.
So this feeds the CONTACT-RESOLUTION problem, not the contact-rich stream: the
name + address is what you then look up in OSM/Places (see enrich/crossref.py) or
search for.

We filter by SIC code, because most new incorporations are holding companies,
dormant shells and consultancies that will never buy a website. The list below is
the trades and consumer-facing businesses that actually will.
"""

from datetime import datetime, timedelta

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("registries")

ADVANCED_SEARCH = "/advanced-search/companies"

# SIC codes worth pitching. Everything else in the daily incorporation feed is
# holding companies, dormant shells, and management consultants.
SIC_WANTED = [
    "56101",  # licensed restaurants
    "56102",  # unlicensed restaurants and cafes
    "56103",  # take-away food shops
    "96020",  # hairdressing and other beauty treatment
    "96040",  # physical well-being activities (spas, massage)
    "93130",  # fitness facilities
    "43210",  # electrical installation
    "43220",  # plumbing, heat and air-conditioning installation
    "43310",  # plastering
    "43390",  # other building completion and finishing
    "41202",  # construction of domestic buildings
    "81300",  # landscape service activities
    "45200",  # maintenance and repair of motor vehicles
    "86230",  # dental practice activities
    "86900",  # other human health activities
    "75000",  # veterinary activities
    "47110",  # retail in non-specialised stores
    "55201",  # holiday centres and villages
    "96090",  # other personal service activities
]


class RegistriesCollector(Collector):
    name = "registries"
    bucket = "registries"

    def available(self) -> tuple[bool, str]:
        if self.mock:
            return True, ""
        if not config.COMPANIES_HOUSE_KEY:
            return False, ("COMPANIES_HOUSE_KEY not set — free key at "
                           "https://developer.company-information.service.gov.uk/")
        return True, ""

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("registries") or {}
            return [s for s in (self._company(c)
                                for c in raw.get("items", [])) if s]

        # The API filters on incorporation DATE, not datetime, so we ask for the
        # window's whole days and let base.run() do the precise cut.
        frm = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        to = datetime.now(since.tzinfo).strftime("%Y-%m-%d")

        out: list[Signal] = []
        for sic in SIC_WANTED:
            resp = self.api.get(
                config.COMPANIES_HOUSE_API + ADVANCED_SEARCH, self.bucket,
                params={
                    "incorporated_from": frm,
                    "incorporated_to": to,
                    "sic_codes": sic,
                    "company_status": "active",
                    "size": 100,
                },
                # Key as USERNAME, empty password. Passing it as the password is
                # a 401 that looks exactly like a bad key.
                auth=(config.COMPANIES_HOUSE_KEY, ""))
            if resp is None:
                continue
            if resp.status_code == 401:
                logger.error(
                    "companies house: 401. The key goes in the USERNAME slot "
                    "with an EMPTY password (curl -u KEY: ...). Also check you "
                    "created a LIVE application, not a test one.")
                return out
            if resp.status_code >= 400:
                logger.warning("companies house: HTTP %d for sic=%s",
                               resp.status_code, sic)
                continue
            try:
                payload = resp.json()
            except ValueError:
                continue
            for item in payload.get("items") or []:
                sig = self._company(item)
                if sig:
                    out.append(sig)

        logger.info("companies house: %d new incorporations in trades/consumer "
                    "SIC codes", len(out))
        return out

    @staticmethod
    def _company(item: dict) -> Signal | None:
        number = item.get("company_number")
        name = item.get("company_name")
        date = item.get("date_of_creation")
        if not (number and name and date):
            return None

        office = item.get("registered_office_address") or {}
        locality = office.get("locality") or ""
        postcode = office.get("postal_code") or ""
        address = ", ".join(x for x in (
            office.get("address_line_1"), locality, postcode) if x)

        return Signal(
            source_uid=f"ch:{number}",
            platform="registries",
            source_detail="companies-house",
            post_title=name,
            body=(f"{name} was incorporated on {date} at {address}. "
                  "A company registered this week does not have a website yet."),
            # Incorporation DATE only — no time is published. Midnight UTC is the
            # honest reading of "that day", not a guess dressed up as precision.
            posted_at=ensure_utc(f"{date}T00:00:00+00:00"),
            signal_type="structural",
            country="GB",
            region=locality,
            geo_method="stated",
            business_type=", ".join(item.get("sic_codes") or []),
            # Companies House publishes no email and no phone. The name + address
            # is the input to a lookup, not a contact.
            contact_channel="form",
            permalink=f"https://find-and-update.company-information.service.gov.uk"
                      f"/company/{number}",
            raw={"address": address, "sic": item.get("sic_codes")},
        )
