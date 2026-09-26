"""Gemini over stdlib urllib — no SDK, same shape as email-automation.

Two things this adds over that one:

  * A CACHE keyed by content hash, in SQLite. Re-running `score` on an unchanged
    corpus must cost zero requests. Without it, every re-run burns the free-tier
    quota re-deciding things it already decided.
  * A pace of 6s, not 5s. The 5.0s in email-automation was tuned against a 15 RPM
    free-tier cap that Google has since stopped publishing per-model (the docs now
    say "check your limits in AI Studio" — they are per-account). We do not know
    your cap, so we pace conservatively, honour the retryDelay Google returns on a
    429, and expose the knob as GEMINI_MIN_INTERVAL.

Mock mode (GEMINI_MOCK=1 / --mock-llm) returns deterministic fake output with
zero network, so the whole parse/validate/regenerate path is testable for free.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

import config
from core import log

logger = log.get("gemini")

_API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
_RETRYABLE = {429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    pass


def _retry_delay(body: str) -> float:
    """Google puts the delay it wants inside the 429 body. Use it."""
    try:
        for detail in json.loads(body).get("error", {}).get("details", []):
            delay = detail.get("retryDelay", "")
            if delay.endswith("s"):
                return float(delay[:-1])
    except (ValueError, AttributeError, TypeError):
        pass
    return 0.0


class Gemini:
    def __init__(self, store=None, mock: bool = False):
        self.api_key = os.getenv(config.GEMINI_API_KEY_ENV, "").strip()
        self.model = config.GEMINI_MODEL
        self.mock = mock or os.getenv("GEMINI_MOCK", "") in {"1", "true", "yes"}
        self.store = store
        self.request_count = 0
        self._last_call = 0.0
        # NO KEY IS NOT MOCK MODE. It used to fall through to _mock(), which does
        # not return "rule scores only" — it INVENTS a verdict (business_type
        # "bakery", region "Leeds", country "GB", stated_problem "mock: has no
        # website and wants one") and an opener, and those were written to SQLite
        # and exported as if a model had said them. A missing key must degrade to
        # "no LLM", never to "fabricated LLM".
        self.enabled = bool(self.mock or self.api_key)
        if not self.enabled:
            logger.warning(
                "%s not set — LLM classification and drafting are OFF. Leads "
                "will carry RULE SCORES ONLY and every opener must be written "
                "by hand.", config.GEMINI_API_KEY_ENV)

    # --- public ---------------------------------------------------------------

    def structured(self, system: str, user: str, schema: dict) -> list[dict]:
        """One structured call. Returns a JSON array. Cached by content hash."""
        if not self.enabled:
            raise GeminiError(f"{config.GEMINI_API_KEY_ENV} is not set")
        key = hashlib.sha1(
            f"{self.model}|{system}|{user}|{json.dumps(schema, sort_keys=True)}"
            .encode("utf-8")).hexdigest()

        if self.store is not None:
            cached = self.store.llm_cached(key)
            if cached is not None:
                logger.debug("llm cache hit")
                return cached.get("items", [])

        items = self._mock(user) if self.mock else self._live(system, user, schema)

        if self.store is not None:
            self.store.llm_store(key, {"items": items})
        return items

    # --- live -----------------------------------------------------------------

    def _live(self, system: str, user: str, schema: dict) -> list[dict]:
        request = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        payload = self._call_with_retries(request)
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiError(f"unexpected Gemini envelope: {exc}") from exc
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"model returned malformed JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise GeminiError("model returned JSON that is not an array")
        return parsed

    def _pace(self) -> None:
        wait = config.GEMINI_MIN_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call_with_retries(self, request: dict) -> dict:
        delay = 10.0
        last = "unknown error"
        for attempt in range(config.GEMINI_HTTP_RETRIES + 1):
            self._pace()
            try:
                return self._post(request)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                last = f"HTTP {exc.code}: {body[:200]}"
                if exc.code not in _RETRYABLE:
                    raise GeminiError(last) from exc
                delay = max(delay, _retry_delay(body))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = f"network error: {exc}"
            if attempt < config.GEMINI_HTTP_RETRIES:
                logger.warning("gemini retry in %.0fs — %s", delay, last)
                time.sleep(delay)
                delay *= 3
        raise GeminiError(f"gave up after {config.GEMINI_HTTP_RETRIES + 1} "
                          f"attempts — {last}")

    def _post(self, request: dict) -> dict:
        req = urllib.request.Request(
            _API_URL.format(model=self.model),
            data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": self.api_key},
            method="POST")
        self.request_count += 1
        with urllib.request.urlopen(req, timeout=config.GEMINI_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # --- mock -----------------------------------------------------------------

    def _mock(self, user: str) -> list[dict]:
        """Deterministic, zero-network. Seeded off each item's id so the same
        input always yields the same verdict — tests stay stable."""
        items: list[dict] = []
        for line in user.splitlines():
            if not line.startswith("ID:"):
                continue
            uid = line[3:].strip()
            seed = int(hashlib.md5(uid.encode()).hexdigest()[:8], 16)
            buyer = seed % 3 != 0          # ~2/3 of mock rows are buyers
            items.append({
                "id": uid,
                "is_lead": buyer,
                "is_seller": not buyer,
                "role": "buyer" if buyer else "seller",
                "tense": "needs_now" if buyer else "already_done",
                "service_wanted": ["web_design", "seo", "both"][seed % 3],
                "business_type": "bakery",
                "business_stage": "just-opened",
                "stated_problem": "mock: has no website and wants one",
                "budget_signal": "",
                "region": "Leeds",
                "country": "GB",
                "confidence": 0.8,
                "intent_score_llm": 75 if buyer else 5,
                # Long enough to clear validate()'s minimum, and deliberately
                # free of the things the validator rejects (no site claims, no
                # invented metrics, no flattery, no exclamation marks) — so a
                # mock run exercises the ACCEPT path, not just the reject path.
                "opener": (
                    "For a shop your size the usual route is a simple one-page "
                    "site with your hours, your location and a way to contact "
                    "you, which you can stand up in a weekend. The thing most "
                    "people skip is claiming the free Google Business listing, "
                    "and that is what actually gets you found locally. Happy to "
                    "point you at the steps if useful. (mock draft for "
                    + uid + ")"),
            })
        return items
