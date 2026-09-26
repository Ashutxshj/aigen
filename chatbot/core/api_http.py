"""HTTP for OFFICIAL APIs. Adapted from /scraper/http_client.py, minus the parts
that are actively wrong for an API:

  * NO proxy rotation. On an authenticated API you are identified by your OAuth
    client id / key, not your IP. Rotating IPs under one Reddit client id does
    not hide anything — it just looks like credential sharing, which is a faster
    ban than being over the rate limit.
  * NO random jitter. Jitter exists to break a detectable fixed cadence when you
    are scraping HTML anonymously. An API expects a steady cadence; jitter only
    makes the run slower.
  * A DESCRIPTIVE bot UA. Reddit explicitly bans fake-browser UAs on its API.

What it does do: spend a token from the persisted bucket before every call,
retry only {429,500,502,503,504}, honour Retry-After, feed the server's own
X-Ratelimit-* headers back into the limiter, and return Optional[Response]
without ever raising.
"""

import random
import time
from typing import Optional

import requests

import config
from core import log
from core.ratelimit import RateLimiter

logger = log.get("api_http")

# A 404/403 is a hard answer — retrying it just burns budget.
#
# 422 is in here for one specific reason. Arctic Shift (the public Reddit archive
# the no-account collector reads) does NOT answer 429 when you push it too hard.
# It answers:
#
#     HTTP 422  {"data": null, "error": "Timeout. Maybe slow down a bit"}
#
# A normal client treats 422 as "your request is malformed" — permanent, don't
# retry — and gives up instantly. So every subreddit silently returned zero and
# the run reported a clean "0 signals", which is precisely the failure-looks-like-
# success trap this repo exists to avoid. It is a rate-limit response wearing a
# validation-error's clothes, so we back off and retry it like one.
_RETRY_STATUS = {422, 429, 500, 502, 503, 504}


class ApiHttp:
    def __init__(self, limiter: RateLimiter, dry_run: bool = False):
        self._limiter = limiter
        self._dry_run = dry_run
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": config.API_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })

    def _backoff_wait(self, attempt: int, retry_after: Optional[str]) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), config.BACKOFF_MAX_SECONDS))
                return
            except (TypeError, ValueError):
                pass  # Retry-After may be an HTTP-date; fall through to backoff
        delay = min(config.BACKOFF_BASE_SECONDS * (2 ** attempt),
                    config.BACKOFF_MAX_SECONDS)
        time.sleep(delay + random.uniform(0, delay * 0.3))  # exp + 30% jitter

    def request(self, method: str, url: str, bucket: str,
                **kwargs) -> Optional[requests.Response]:
        """Returns a Response, or None if the call was skipped/failed. Never
        raises — a dead collector must not kill the run."""
        if self._dry_run:
            logger.info("[dry-run] would %s %s", method, url)
            return None
        if not self._limiter.acquire(bucket):
            return None                     # daily quota gone: skip, don't wait

        kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
        last = "unknown error"

        for attempt in range(config.MAX_RETRIES):
            try:
                resp = self._session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
                logger.warning("%s %s (attempt %d/%d)", type(exc).__name__, url,
                               attempt + 1, config.MAX_RETRIES)
                if attempt < config.MAX_RETRIES - 1:
                    self._backoff_wait(attempt, None)
                continue

            # Believe the server's own accounting over our config table.
            self._limiter.observe_headers(bucket, resp.headers)

            if resp.status_code in _RETRY_STATUS:
                retry_after = resp.headers.get("Retry-After")
                if resp.status_code == 429:
                    # Park the BUCKET, not just this call: a 429 means every
                    # other collector sharing this key must wait too.
                    try:
                        self._limiter.penalise(bucket, float(retry_after or 60))
                    except (TypeError, ValueError):
                        self._limiter.penalise(bucket, 60.0)
                last = f"HTTP {resp.status_code}"
                logger.warning("HTTP %d on %s (attempt %d/%d)", resp.status_code,
                               url, attempt + 1, config.MAX_RETRIES)
                if attempt < config.MAX_RETRIES - 1:
                    self._backoff_wait(attempt, retry_after)
                continue

            return resp

        logger.error("giving up on %s after %d attempts — %s", url,
                     config.MAX_RETRIES, last)
        return None

    def get(self, url: str, bucket: str, **kwargs) -> Optional[requests.Response]:
        return self.request("GET", url, bucket, **kwargs)

    def post(self, url: str, bucket: str, **kwargs) -> Optional[requests.Response]:
        return self.request("POST", url, bucket, **kwargs)

    def get_json(self, url: str, bucket: str, **kwargs) -> Optional[dict | list]:
        resp = self.get(url, bucket, **kwargs)
        if resp is None:
            return None
        if resp.status_code >= 400:
            logger.warning("HTTP %d on %s: %s", resp.status_code, url,
                           resp.text[:200])
            return None
        try:
            return resp.json()
        except ValueError:
            logger.error("non-JSON response from %s: %s", url, resp.text[:200])
            return None
