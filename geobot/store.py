"""Tiny JSON-file store. GitHub Actions commits it back to the repo each run,
so state persists across runs without any external database.

Schema:
{
  "challenges": [{"token": "...", "date": "2026-06-23", "url": "...", "map": "normal"}],
  "scores":     [{"date": "2026-06-23", "token": "...", "user_id": "...",
                  "name": "...", "score": 1234}]
}
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

from .maps import weight

STORE_PATH = os.environ.get("GEO_STORE", "data/store.json")


def _load() -> dict:
    if not os.path.exists(STORE_PATH):
        return {"challenges": [], "scores": []}
    with open(STORE_PATH) as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def add_challenge(
    token: str, url: str, map_name: str, on: date | None = None
) -> None:
    data = _load()
    on = on or date.today()
    data["challenges"].append(
        {"token": token, "url": url, "date": on.isoformat(), "map": map_name}
    )
    _save(data)


def recent_tokens(days: int = 7) -> list[str]:
    data = _load()
    cutoff = date.today() - timedelta(days=days)
    return [
        c["token"]
        for c in data["challenges"]
        if date.fromisoformat(c["date"]) >= cutoff
    ]


def date_for_token(token: str) -> str | None:
    data = _load()
    for c in data["challenges"]:
        if c["token"] == token:
            return c["date"]
    return None


def upsert_scores(token: str, scores: list[dict]) -> None:
    """Replace stored scores for a token with the latest fetched set."""
    data = _load()
    d = date_for_token(token) or date.today().isoformat()
    data["scores"] = [s for s in data["scores"] if s["token"] != token]
    for s in scores:
        data["scores"].append(
            {
                "date": d,
                "token": token,
                "user_id": s["user_id"],
                "name": s["name"],
                "score": s["score"],
            }
        )
    _save(data)


def rolling_leaderboard(days: int = 7) -> list[dict]:
    """Aggregate best-per-day scores over the trailing window.

    Sums each player's score across the last `days` challenges, scaling each
    challenge by its map's `weight` so an easier map doesn't dominate.
    Returns [{'name', 'total', 'rounds'}] sorted high to low.
    """
    data = _load()
    cutoff = date.today() - timedelta(days=days)
    token_map = {c["token"]: c.get("map") for c in data["challenges"]}
    agg: dict[str, dict] = {}
    for s in data["scores"]:
        if date.fromisoformat(s["date"]) < cutoff:
            continue
        key = s["user_id"] or s["name"]
        e = agg.setdefault(key, {"name": s["name"], "total": 0.0, "rounds": 0})
        e["total"] += s["score"] * weight(token_map.get(s["token"]))
        e["rounds"] += 1
        e["name"] = s["name"]
    rows = list(agg.values())
    for r in rows:
        r["total"] = round(r["total"])
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows
