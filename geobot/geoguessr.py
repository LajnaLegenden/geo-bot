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
            amount = player.get("totalScore", {}).get("amount", 0)
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
                    # ponytail: API returns amount as a string; coerce so the store stays numeric
                    "score": int(amount) if amount else 0,
                    "pin": player.get("pin", {}).get("url"),
                    "guesses": guesses,
                }
            )
        return {"countries": countries, "players": players}
