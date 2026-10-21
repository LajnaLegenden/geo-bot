"""Thin wrapper over GeoGuessr's private endpoints.

GeoGuessr has no official public API. These endpoints are reverse-engineered
and can change without notice. Auth is via the _ncfa session cookie, which you
grab from a logged-in browser session (DevTools > Application > Cookies).
"""
from __future__ import annotations

import re

import requests

BASE = "https://www.geoguessr.com/api"


class GeoGuessr:
    def __init__(self, ncfa_cookie: str):
        self.s = requests.Session()
        self.s.cookies.set("_ncfa", ncfa_cookie, domain="www.geoguessr.com")
        self.s.headers.update({"Content-Type": "application/json"})

    def check_auth(self) -> bool:
        """Return True if the _ncfa cookie is still valid.

        Pings an authenticated endpoint; 401/403 means the cookie is dead
        (expired, password changed, or logged out in that browser session).
        """
        try:
            r = self.s.get(f"{BASE}/v3/profiles/me", timeout=15)
        except requests.RequestException:
            return False
        return r.status_code == 200

    def create_challenge(
        self,
        map_id: str = "world",          # built-in "world" map, or a custom map slug/id
        time_limit: int = 0,            # seconds per round, 0 = unlimited
        forbid_moving: bool = False,
        forbid_zooming: bool = False,
        forbid_rotating: bool = False,
    ) -> str:
        """Create a daily challenge and return its token."""
        payload = {
            "map": map_id,
            "timeLimit": time_limit,
            "forbidMoving": forbid_moving,
            "forbidZooming": forbid_zooming,
            "forbidRotating": forbid_rotating,
        }
        r = self.s.post(f"{BASE}/v3/challenges", json=payload)
        r.raise_for_status()
        return r.json()["token"]

    @staticmethod
    def challenge_url(token: str) -> str:
        return f"https://www.geoguessr.com/challenge/{token}"

    def resolve_map(self, pasted: str) -> dict:
        """Resolve a pasted map id / slug / URL to {map_id, name, thumbnail}.

        Used by the "paste + validate" map picker. Raises requests.HTTPError if
        the map doesn't exist. The response shape is best-effort against the
        unofficial /api/maps/{id} endpoint — adjust the key lookups below if the
        live API differs.
        """
        map_id = self._map_id_from(pasted)
        r = self.s.get(f"{BASE}/maps/{map_id}", timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            "map_id": map_id,
            "name": data.get("name") or map_id,
            "thumbnail": self._map_thumbnail(data),
        }

    @staticmethod
    def _map_id_from(pasted: str) -> str:
        """Pull the id/slug out of a full URL (…/maps/<id>[/play]) or return the
        pasted value as-is if it's already a bare id/slug."""
        p = pasted.strip()
        m = re.search(r"/maps/([^/?#]+)", p)
        return m.group(1) if m else p

    @staticmethod
    def _map_thumbnail(data: dict) -> str | None:
        images = data.get("images") or {}
        path = images.get("backgroundLarge") or data.get("imageUrl")
        if not path:
            return None
        if path.startswith("http"):
            return path
        return "https://www.geoguessr.com" + (path if path.startswith("/") else "/" + path)

    def highscores(self, token: str, limit: int = 50) -> dict:
        """Return {'countries': [cc×5], 'players': [{...}]} for everyone who played.

        `countries` are the actual-location country codes per round (same for all
        players in a challenge). Each player carries their per-round `guesses`
        (points/distance/time/miss) and avatar `pin`, plus the total `score`.
        """
        r = self.s.get(
            f"{BASE}/v3/results/highscores/{token}",
            params={"friends": "false", "limit": limit},
        )
        r.raise_for_status()
        items = r.json().get("items", [])

        # rounds are identical across players; read the actual-location country
        # codes once from the first item (streakLocationCode is set even on world).
        rounds = items[0].get("game", {}).get("rounds", []) if items else []
        countries = [(rd.get("streakLocationCode") or "").lower() or None for rd in rounds]

        players = []
        for item in items:
            player = item.get("game", {}).get("player", {})
            # API renamed totalScore.amount (string) to totalScoreInPoints (int); keep old key as fallback
            amount = player.get("totalScoreInPoints") or player.get("totalScore", {}).get("amount", 0)
            guesses = [
                {
                    "pts": int(g.get("roundScoreInPoints") or 0),
                    "dist": g.get("distanceInMeters"),
                    "t": g.get("time"),
                    "miss": bool(
                        (g.get("timedOut") or g.get("skippedRound"))
                        and not g.get("timedOutWithGuess")
                    ),
                }
                for g in player.get("guesses", [])
            ]
            players.append(
                {
                    "name": player.get("nick", "unknown"),
                    "user_id": player.get("id", ""),
                    # ponytail: legacy amount was a string; coerce so the store stays numeric
                    "score": int(amount) if amount else 0,
                    "pin": player.get("pin", {}).get("url"),
                    "guesses": guesses,
                }
            )
        return {"countries": countries, "players": players}
