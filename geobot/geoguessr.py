"""Thin wrapper over GeoGuessr's private endpoints.

GeoGuessr has no official public API. These endpoints are reverse-engineered
and can change without notice. Auth is via the _ncfa session cookie, which you
grab from a logged-in browser session (DevTools > Application > Cookies).
"""
from __future__ import annotations

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

    def highscores(self, token: str, limit: int = 50) -> list[dict]:
        """Return [{'name', 'user_id', 'score'}] for everyone who has played."""
        r = self.s.get(
            f"{BASE}/v3/results/highscores/{token}",
            params={"friends": "false", "limit": limit},
        )
        r.raise_for_status()
        out = []
        for item in r.json().get("items", []):
            game = item.get("game", {})
            player = game.get("player", {})
            amount = player.get("totalScore", {}).get("amount", 0)
            out.append(
                {
                    "name": player.get("nick", "unknown"),
                    "user_id": player.get("id", ""),
                    # ponytail: API returns amount as a string; coerce so the store stays numeric
                    "score": int(amount) if amount else 0,
                }
            )
        return out
