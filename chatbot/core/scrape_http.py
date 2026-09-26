"""HTTP for HTML pages nobody gave us an API for.

This is the half where the /scraper anti-ban kit is CORRECT: we are anonymous,
the server has no contract with us, and a fixed cadence from one IP with one
User-Agent is exactly what a bot detector looks for. So here we do rotate
proxies, do jitter, and do vary the UA.

We also obey robots.txt Disallow, which the sibling scrapers do not (they parse
robots.txt only to harvest Sitemap: lines). That single rule is why Craigslist is
absent from this repo: its robots.txt disallows /search, and its RSS feeds are
served from /search?format=rss. "Collect Craigslist" and "obey robots.txt" cannot
both be true, so we kept the rule and dropped the source.
"""

import random
import threading
import time
import urllib.robotparser as robotparser
from typing import Optional
from urllib.parse import urlparse

import requests

import config
from core import log
from core.ratelimit import RateLimiter

logger = log.get("scrape_http")

_RETRY_STATUS = {429, 500, 502, 503, 504}


class ProxyPool:
    """Round-robin with per-proxy failure strikes. Lifted from
    /scraper/http_client.py, which had this part right."""

    def __init__(self, proxies: list[str], max_failures: int):
        self._proxies = list(dict.fromkeys(p.strip() for p in proxies if p.strip()))
        self._failures: dict[str, int] = {p: 0 for p in self._proxies}
        self._idx = 0
        self._max_failures = max_failures
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def next(self) -> Optional[str]:
        with self._lock:
            if not self._proxies:
                return None
            self._idx %= len(self._proxies)
            proxy = self._proxies[self._idx]
            self._idx += 1
            return proxy

    def report_failure(self, proxy: Optional[str]) -> None:
        if not proxy:
            return
        with self._lock:
            if proxy not in self._failures:
                return
            self._failures[proxy] += 1
            if self._failures[proxy] >= self._max_failures:
                self._proxies = [p for p in self._proxies if p != proxy]
                self._failures.pop(proxy, None)
                logger.warning("dropped dead proxy (%d left)", len(self._proxies))

    def report_success(self, proxy: Optional[str]) -> None:
        if proxy and proxy in self._failures:
            self._failures[proxy] = 0


def _load_proxies() -> list[str]:
    out: list[str] = []
    if config.PROXY_LIST:
        out += [p for p in config.PROXY_LIST.split(",") if p.strip()]
    if config.PROXY_FILE:
        try:
            with open(config.PROXY_FILE, encoding="utf-8") as fh:
                out += [ln.strip() for ln in fh
                        if ln.strip() and not ln.startswith("#")]
        except OSError as exc:
            logger.warning("could not read PROXY_FILE: %s", exc)
    return out


class ScrapeHttp:
    def __init__(self, limiter: RateLimiter, dry_run: bool = False):
        self._limiter = limiter
        self._dry_run = dry_run
        self._pool = ProxyPool(_load_proxies(), config.PROXY_MAX_FAILURES)
        self._session = requests.Session()
        self._robots: dict[str, Optional[robotparser.RobotFileParser]] = {}
        if self._pool.enabled:
            logger.info("proxy rotation active")

    # --- robots.txt ----------------------------------------------------------

    def allowed(self, url: str) -> bool:
        """False if the site's robots.txt disallows this path for us.

        A robots.txt we cannot fetch is treated as ALLOW, not DENY: a transient
        503 on robots.txt should not silently disable a collector for a day. A
        robots.txt that exists and says no is honoured.
        """
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
            except Exception as exc:                      # network/parse failure
                logger.debug("robots.txt unreadable for %s (%s) — allowing",
                             origin, exc)
                self._robots[origin] = None
            else:
                self._robots[origin] = rp
        rp = self._robots[origin]
        if rp is None:
            return True
        ua = config.BROWSER_USER_AGENTS[0]
        ok = rp.can_fetch(ua, url)
        if not ok:
            logger.warning("robots.txt DISALLOWS %s — skipping", url)
        return ok

    # --- requests ------------------------------------------------------------

    def _polite_sleep(self) -> None:
        lo, hi = config.JITTER_MIN_SECONDS, config.JITTER_MAX_SECONDS
        if hi >= lo > 0:
            time.sleep(random.uniform(lo, hi))

    def get(self, url: str, bucket: str = "web",
            **kwargs) -> Optional[requests.Response]:
        if self._dry_run:
            logger.info("[dry-run] would GET %s", url)
            return None
        if not self.allowed(url):
            return None
        if not self._limiter.acquire(bucket):
            return None

        kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("User-Agent", random.choice(config.BROWSER_USER_AGENTS))
        headers.setdefault("Accept-Language", "en-GB,en;q=0.9")

        for attempt in range(config.MAX_RETRIES):
            self._polite_sleep()
            proxy = self._pool.next()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            try:
                resp = self._session.get(url, headers=headers, proxies=proxies,
                                         **kwargs)
            except requests.RequestException as exc:
                self._pool.report_failure(proxy)
                logger.warning("%s on %s (attempt %d/%d)", type(exc).__name__,
                               url, attempt + 1, config.MAX_RETRIES)
                continue

            if resp.status_code in _RETRY_STATUS:
                self._pool.report_failure(proxy)
                logger.warning("HTTP %d on %s (attempt %d/%d)", resp.status_code,
                               url, attempt + 1, config.MAX_RETRIES)
                delay = min(config.BACKOFF_BASE_SECONDS * (2 ** attempt),
                            config.BACKOFF_MAX_SECONDS)
                time.sleep(delay + random.uniform(0, delay * 0.3))
                continue

            self._pool.report_success(proxy)
            return resp

        logger.error("giving up on %s", url)
        return None
