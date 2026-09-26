"""Bluesky — free, and you already have the credentials.

`app.bsky.feed.searchPosts` REQUIRES auth. The unauthenticated appview
(`public.api.bsky.app`) only does *actor* search — people, not posts — which is
useless here. So we log in with the app password you already set
(`BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD`).

An **app password is not your account password**. It is a scoped credential you
generate in Settings → App Passwords, it cannot change your password or delete
your account, and you can revoke it in one click. This is the sanctioned way to
do exactly this, which is why it costs nothing and carries no ban risk.

Honest expectation: **Bluesky has the best API and the wrong audience.** Plumbers
and dentists are not on Bluesky; developers and journalists are. Verified today —
a search for "need a website for my business" returned ten posts, of which most
were chatter and one was a hosting-affiliate spammer. It costs one request per
query and it occasionally turns up an indie founder, so it earns its place. It
will not carry the funnel.
"""

import json
from datetime import datetime

import config
from collectors.base import Collector
from core import log
from core.models import Signal, ensure_utc

logger = log.get("bluesky")

SESSION = f"{config.BLUESKY_PDS}/xrpc/com.atproto.server.createSession"
SEARCH = f"{config.BLUESKY_PDS}/xrpc/app.bsky.feed.searchPosts"


class BlueskyCollector(Collector):
    name = "bluesky"
    bucket = "bluesky"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._token: str | None = None

    def available(self) -> tuple[bool, str]:
        if self.mock:
            return True, ""
        if not (config.BLUESKY_HANDLE and config.BLUESKY_APP_PASSWORD):
            return False, ("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set. "
                           "Free: Bluesky Settings -> App Passwords. Post search "
                           "requires auth; the public appview cannot do it.")
        return True, ""

    def _auth(self) -> str | None:
        if self._token:
            return self._token
        resp = self.api.post(
            SESSION, self.bucket,
            data=json.dumps({"identifier": config.BLUESKY_HANDLE,
                             "password": config.BLUESKY_APP_PASSWORD}),
            headers={"Content-Type": "application/json"})
        if resp is None or resp.status_code != 200:
            logger.error("bluesky auth failed (%s) — check the APP PASSWORD, not "
                         "your account password",
                         resp.status_code if resp else "no response")
            return None
        try:
            self._token = resp.json().get("accessJwt")
        except ValueError:
            return None
        logger.info("bluesky: authenticated as %s", config.BLUESKY_HANDLE)
        return self._token

    def fetch(self, since: datetime) -> list[Signal]:
        if self.mock:
            raw = self.fixture("bluesky") or {}
            return [s for s in (self._post(p) for p in raw.get("posts", [])) if s]

        token = self._auth()
        if not token:
            return []

        out: list[Signal] = []
        for query in config.BLUESKY_QUERIES:
            payload = self.api.get_json(
                SEARCH, self.bucket,
                params={"q": query, "limit": 50, "sort": "latest"},
                headers={"Authorization": f"Bearer {token}"})
            if not payload:
                continue
            for post in payload.get("posts") or []:
                sig = self._post(post)
                if sig and sig.posted_at >= since:
                    out.append(sig)

        seen: dict[str, Signal] = {}
        for sig in out:
            seen.setdefault(sig.source_uid, sig)
        return list(seen.values())

    @staticmethod
    def _post(post: dict) -> Signal | None:
        uri = post.get("uri")
        record = post.get("record") or {}
        author = post.get("author") or {}
        handle = author.get("handle") or ""
        created = record.get("createdAt")
        text = record.get("text") or ""
        if not uri or not created or not text:
            return None

        # at://did:plc:xxx/app.bsky.feed.post/3kabc -> the rkey is the last part.
        rkey = uri.rsplit("/", 1)[-1]

        return Signal(
            source_uid=f"bsky:{uri}",
            platform="bluesky",
            source_detail="bluesky",
            username=handle,
            person_key=f"@{handle}@bluesky" if handle else "",
            permalink=f"https://bsky.app/profile/{handle}/post/{rkey}",
            post_title="",
            body=text,
            posted_at=ensure_utc(created),
            signal_type="stated_problem",
            contact_channel="public_reply",
            raw={"likes": post.get("likeCount")},
        )
