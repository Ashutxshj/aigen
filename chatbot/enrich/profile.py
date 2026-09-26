"""Read the author's own recent posts to work out what their business actually is.

This is the module that earns the reply. Anyone can quote the post they found you
in. Knowing that the person asking "how do I get a website" also posted last week
in r/EtsySellers about their candle business, in Leeds, and is worried about
Christmas orders — that is what turns a generic pitch into a message somebody
answers.

It is also the module that costs the most requests, so it only runs on leads that
already scored well. Never enrich a maybe.
"""

from datetime import datetime

import config
from core import log
from core.models import Signal, ensure_utc
from enrich import contact

logger = log.get("profile")

REDDIT_API = "https://oauth.reddit.com"
HN_ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"
ARCTIC_POSTS = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"


class Profiler:
    def __init__(self, api, reddit_collector, mock: bool = False):
        self.api = api
        self.reddit = reddit_collector      # reuse its token
        self.mock = mock

    def history(self, signal: Signal, limit: int = 25) -> list[str]:
        """The author's recent text, newest first. [] if we cannot get it."""
        if self.mock:
            return [f"(mock history for {signal.username})"]

        if signal.platform == "reddit" and signal.username:
            return self._reddit_history(signal.username, limit)
        if signal.platform == "hackernews" and signal.username:
            return self._hn_history(signal.username, limit)
        return []

    def _reddit_history(self, username: str, limit: int) -> list[str]:
        """The author's recent posts and comments.

        Two routes, because the OAuth one needs credentials the user may
        deliberately not have (see collectors/reddit_public.py): if there is no
        token, fall back to the same public archive the collector reads. Reddit's
        own /user/x.json is 403 Blocked unauthenticated, so there is no third way.
        """
        token = getattr(self.reddit, "_auth", lambda: None)()
        if token:
            return self._reddit_history_oauth(username, limit, token)
        return self._reddit_history_public(username, limit)

    def _reddit_history_public(self, username: str, limit: int) -> list[str]:
        out: list[str] = []
        for url, field in ((ARCTIC_COMMENTS, "body"), (ARCTIC_POSTS, "selftext")):
            payload = self.api.get_json(
                url, "arcticshift",
                params={"author": username, "limit": limit, "sort": "desc"},
                headers={"User-Agent": config.API_USER_AGENT})
            if not payload:
                continue
            for item in payload.get("data") or []:
                sub = item.get("subreddit") or ""
                text = (item.get(field) or item.get("title") or "").strip()
                if text and text not in ("[deleted]", "[removed]"):
                    out.append(f"[r/{sub}] {text[:400]}")
        return out[:limit]

    def _reddit_history_oauth(self, username: str, limit: int,
                              token: str) -> list[str]:
        out: list[str] = []
        for path in (f"/user/{username}/comments", f"/user/{username}/submitted"):
            resp = self.api.get(
                f"{REDDIT_API}{path}", "reddit",
                params={"limit": limit, "sort": "new"},
                headers={"Authorization": f"bearer {token}",
                         "User-Agent": config.REDDIT_USER_AGENT})
            if resp is None or resp.status_code >= 400:
                continue
            try:
                payload = resp.json()
            except ValueError:
                continue
            for child in (payload.get("data") or {}).get("children") or []:
                data = child.get("data") or {}
                sub = data.get("subreddit") or ""
                text = (data.get("body") or data.get("selftext")
                        or data.get("title") or "").strip()
                if text:
                    out.append(f"[r/{sub}] {text[:400]}")
        return out[:limit]

    def _hn_history(self, username: str, limit: int) -> list[str]:
        payload = self.api.get_json(
            HN_ALGOLIA, "hackernews",
            params={"tags": f"author_{username}", "hitsPerPage": limit})
        if not payload:
            return []
        out = []
        for hit in payload.get("hits", []):
            text = (hit.get("comment_text") or hit.get("story_text")
                    or hit.get("title") or "")
            if text:
                out.append(text[:400])
        return out

    def enrich(self, signal: Signal) -> dict[str, str]:
        """Contact + geo + a compact 'what this person is about' summary.

        The summary is raw source material for the drafter, NOT a claim. Every
        fact in the eventual opener still has to be traceable to text the person
        actually wrote — see draft/generate.py's validator.
        """
        posts = self.history(signal)
        blob = signal.text() + "\n" + "\n".join(posts)

        found = contact.extract(blob, signal.source_detail)

        # Prefer whatever the collector already knew; only fill the gaps. An
        # OSM phone number is a fact; a regex hit on a post body is a guess.
        out = {
            "email": signal.email or found["email"],
            "phone": signal.phone or found["phone"],
            "website": signal.website or found["website"],
            "country": signal.country or found["country"],
            "geo_method": signal.geo_method or found["geo_method"],
        }
        out["contact_channel"] = contact.channel(
            signal.platform, out["email"], out["phone"])
        out["author_context"] = " | ".join(p.replace("\n", " ")
                                           for p in posts[:6])[:1500]
        return out
