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


def week_start(today: date | None = None) -> date:
    """Monday of the current (or given) week — the weekly board's reset point."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def _token_map(data: dict) -> dict[str, str | None]:
    return {c["token"]: c.get("map") for c in data["challenges"]}


def _weighted_board(scores: list[dict], token_map: dict) -> list[dict]:
    """Sum each player's scores, scaling by map `weight` so an easier map
    doesn't dominate. Returns [{'name', 'total', 'rounds'}] high to low."""
    agg: dict[str, dict] = {}
    for s in scores:
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


def weekly_leaderboard() -> list[dict]:
    """Weighted board for the current week (scores since Monday)."""
    data = _load()
    start = week_start()
    scores = [
        s for s in data["scores"] if date.fromisoformat(s["date"]) >= start
    ]
    return _weighted_board(scores, _token_map(data))


def all_time_leaderboard() -> list[dict]:
    """Weighted board over every recorded score."""
    data = _load()
    return _weighted_board(data["scores"], _token_map(data))


def map_stats() -> list[dict]:
    """Per-map raw-score stats: [{'map', 'games', 'avg', 'best'}].

    Challenges predating map tracking have no `map` — treat them as 'normal',
    the long-standing daily map. Averages use raw scores (single-map, so no
    cross-map weighting needed)."""
    data = _load()
    token_map = {c["token"]: (c.get("map") or "normal") for c in data["challenges"]}
    by: dict[str, dict] = {}
    for s in data["scores"]:
        m = token_map.get(s["token"], "normal")
        e = by.setdefault(m, {"map": m, "games": 0, "_total": 0, "best": 0})
        e["games"] += 1
        e["_total"] += s["score"]
        e["best"] = max(e["best"], s["score"])
    rows = []
    for e in sorted(by.values(), key=lambda e: e["map"]):
        rows.append(
            {
                "map": e["map"],
                "games": e["games"],
                "avg": round(e["_total"] / e["games"]) if e["games"] else 0,
                "best": e["best"],
            }
        )
    return rows


def player_stats() -> list[dict]:
    """Per-player raw-score stats, sorted by games desc:
    [{'name', 'games', 'avg', 'best', 'per_map': {map: {games, avg, best}}}]."""
    data = _load()
    token_map = {c["token"]: (c.get("map") or "normal") for c in data["challenges"]}
    by: dict[str, dict] = {}
    for s in data["scores"]:
        key = s["user_id"] or s["name"]
        p = by.setdefault(
            key, {"name": s["name"], "games": 0, "_total": 0, "best": 0, "_maps": {}}
        )
        p["name"] = s["name"]
        p["games"] += 1
        p["_total"] += s["score"]
        p["best"] = max(p["best"], s["score"])
        m = token_map.get(s["token"], "normal")
        mm = p["_maps"].setdefault(m, {"games": 0, "_total": 0, "best": 0})
        mm["games"] += 1
        mm["_total"] += s["score"]
        mm["best"] = max(mm["best"], s["score"])
    rows = []
    for p in sorted(by.values(), key=lambda p: p["games"], reverse=True):
        per_map = {
            m: {
                "games": v["games"],
                "avg": round(v["_total"] / v["games"]),
                "best": v["best"],
            }
            for m, v in sorted(p["_maps"].items())
        }
        rows.append(
            {
                "name": p["name"],
                "games": p["games"],
                "avg": round(p["_total"] / p["games"]),
                "best": p["best"],
                "per_map": per_map,
            }
        )
    return rows


if __name__ == "__main__":  # python -m geobot.store — self-check
    assert week_start(date(2026, 7, 8)) == date(2026, 7, 6)  # Wed -> Mon
    assert week_start(date(2026, 7, 6)) == date(2026, 7, 6)  # Mon -> same Mon
    assert week_start(date(2026, 7, 12)) == date(2026, 7, 6)  # Sun -> that Mon

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        STORE_PATH = os.path.join(d, "store.json")
        _save(
            {
                "challenges": [
                    {"token": "t1", "date": "2026-07-06", "url": "", "map": "normal"},
                    {"token": "t2", "date": "2026-07-06", "url": "", "map": "fast"},
                ],
                "scores": [
                    {"date": "2026-07-06", "token": "t1", "user_id": "a", "name": "A", "score": 1000},
                    {"date": "2026-07-06", "token": "t2", "user_id": "a", "name": "A", "score": 1000},
                    {"date": "2026-07-06", "token": "t1", "user_id": "b", "name": "B", "score": 500},
                ],
            }
        )
        ms = {m["map"]: m for m in map_stats()}
        assert ms["normal"]["avg"] == 750 and ms["normal"]["best"] == 1000, ms
        assert ms["fast"]["games"] == 1, ms
        # A: 1000*1.0 (normal) + 1000*1.75 (fast) = 2750; B: 500
        board = all_time_leaderboard()
        assert board[0]["name"] == "A" and board[0]["total"] == 2750, board
        ps = {p["name"]: p for p in player_stats()}
        assert ps["A"]["games"] == 2 and ps["A"]["per_map"]["fast"]["best"] == 1000, ps
    print("store ok")
