"""The Collector contract.

A collector fetches raw Signals from one source and knows three things about
itself: its name, its rate-limit bucket key, and whether it is currently usable
(some need a key the user may not have set).

`available()` returning False is a normal, expected state, not an error. A user
without a Bluesky app password should see one clean "skipped: no credentials"
line and a run that still works — not a crash, and not a silent empty result that
looks like "there were no leads today".
"""

import abc
import json
import os
from datetime import datetime

import config
from core import log
from core.models import Signal

logger = log.get("collector")


class Collector(abc.ABC):
    name: str = "base"
    bucket: str = "web"

    def __init__(self, api, scraper, store, mock: bool = False):
        self.api = api
        self.scraper = scraper
        self.store = store
        self.mock = mock
        # Set by run(). The Runs sheet is the thing you read when yield drops, so
        # "the collector threw" and "the collector found nothing" must not both
        # show up there as 0 fetched / 0 errors.
        self.errors = 0

    def available(self) -> tuple[bool, str]:
        """(usable?, why not). Override when the source needs credentials."""
        return True, ""

    @abc.abstractmethod
    def fetch(self, since: datetime) -> list[Signal]:
        """Signals posted at or after `since` (aware UTC)."""

    # --- fixtures -------------------------------------------------------------

    def fixture(self, name: str):
        """Recorded JSON for --mock, so the whole pipeline runs offline."""
        path = os.path.join(config.FIXTURES_DIR, f"{name}.json")
        if not os.path.exists(path):
            logger.warning("%s: no fixture at %s", self.name, path)
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def run(self, since: datetime) -> list[Signal]:
        self.errors = 0
        ok, why = self.available()
        if not ok:
            logger.info("%s: skipped — %s", self.name, why)
            return []
        try:
            signals = self.fetch(since)
        except Exception:
            # A broken collector must not take the run down, but it must be
            # LOUD. logger.exception bumps the error counter, main.py reports a
            # non-clean run, and self.errors puts it in the Runs sheet so a
            # crash never reads as "there was nothing to find today".
            logger.exception("%s: collector failed", self.name)
            self.errors = 1
            return []
        fresh = [s for s in signals if s.posted_at >= since]
        if len(fresh) != len(signals):
            logger.debug("%s: dropped %d signals older than the window",
                         self.name, len(signals) - len(fresh))

        if self.mock:
            fresh = [self._neuter(s) for s in fresh]

        logger.info("%s: %d signals in window", self.name, len(fresh))
        return fresh

    @staticmethod
    def _neuter(signal: Signal) -> Signal:
        """Make a mock signal's permalink impossible to open.

        Sanitising the FIXTURE FILES is not enough, because collectors BUILD the
        permalink from an id ("https://news.ycombinator.com/item?id=" + objectID).
        Reddit and HN ids are just base36/integers, so an invented fixture id is
        a perfectly valid REAL id: "aaa3" resolves to a genuine 2005 thread, and
        HN item 40000001 is somebody's actual comment. A mock lead that opens a
        stranger's twenty-year-old post about Kurzweil is worse than a broken
        link — it makes fake output look convincingly real.

        So the ONE place every collector's output passes through rewrites the host
        to a reserved-invalid domain. RFC 2606 guarantees .invalid never resolves.
        """
        if signal.permalink:
            signal.permalink = (
                "https://mock.invalid/NOT-A-REAL-LEAD/"
                f"{signal.platform}/{signal.source_uid}")
        return signal
