"""Tiny JSON-file store. GitHub Actions commits it back to the repo each run,
so state persists across runs without any external database.

Schema:
{
  "challenges": [{"token": "...", "date": "2026-06-23", "url": "...", "map": "normal",
                  "countries": ["us", "fr", ...]}],  # actual-location code per round (5)
  "scores":     [{"date": "2026-06-23", "token": "...", "user_id": "...",
                  "name": "...", "score": 1234, "pin": "https://.../avatar.png",
                  "guesses": [{"pts": 5000, "dist": 12.3, "t": 42, "miss": false}, ...]}]
}

`countries`, `pin`, `guesses` are added by newer fetches; rows/challenges predating
them simply lack the keys, and the stat functions below skip what's missing.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

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


def all_tokens() -> list[str]:
    """Every challenge token, oldest first — the backfill's fetch set."""
    return [c["token"] for c in _load()["challenges"]]


def date_for_token(token: str) -> str | None:
    data = _load()
    for c in data["challenges"]:
        if c["token"] == token:
            return c["date"]
    return None


def upsert_scores(token: str, result: dict) -> None:
    """Replace stored scores for a token with the latest fetched set.

    `result` is `GeoGuessr.highscores`'s dict: {'countries': [...], 'players': [...]}.
    The per-round actual-location `countries` land on the challenge entry (shared
    across players); per-player `pin` + `guesses` land on each score row.
    """
    data = _load()
    d = date_for_token(token) or date.today().isoformat()
    countries = result.get("countries") or []
    if countries:  # don't wipe good data if a fetch came back empty
        for c in data["challenges"]:
            if c["token"] == token:
                c["countries"] = countries
    data["scores"] = [s for s in data["scores"] if s["token"] != token]
    for s in result["players"]:
        data["scores"].append(
            {
                "date": d,
                "token": token,
                "user_id": s["user_id"],
                "name": s["name"],
                "score": s["score"],
                "pin": s.get("pin"),
                "guesses": s.get("guesses", []),
            }
        )
    _save(data)


def week_start(today: date | None = None) -> date:
    """Monday of the current (or given) week — the weekly board's reset point."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def _token_weight(data: dict) -> dict[str, float]:
    """Per-challenge score multiplier stamped by the loader/importer; 1.0 when
    absent, so single-map and legacy data stays unweighted."""
    return {c["token"]: c.get("weight", 1.0) for c in data["challenges"]}


def _weighted_board(scores: list[dict], token_weight: dict) -> list[dict]:
    """Sum each player's scores, scaling by each challenge's `weight` so an easier
    map doesn't dominate. Returns [{'name', 'total', 'rounds'}] high to low."""
    agg: dict[str, dict] = {}
    for s in scores:
        key = s["user_id"] or s["name"]
        e = agg.setdefault(key, {"key": key, "name": s["name"], "total": 0.0, "rounds": 0})
        e["total"] += s["score"] * token_weight.get(s["token"], 1.0)
        e["rounds"] += 1
        e["name"] = s["name"]
    rows = list(agg.values())
    for r in rows:
        r["total"] = round(r["total"])
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def weekly_leaderboard(data: dict | None = None) -> list[dict]:
    """Weighted board for the current week (scores since Monday)."""
    data = data if data is not None else _load()
    start = week_start()
    scores = [
        s for s in data["scores"] if date.fromisoformat(s["date"]) >= start
    ]
    return _weighted_board(scores, _token_weight(data))


def players_not_played_today(data: dict, today: str) -> list[dict]:
    """This-week's players who haven't completed *every* challenge dated `today` (a
    league-tz ISO date string). 'This week' = any score since Monday.

    Returns [{'key', 'name'}] — the `key` is the same player key the rest of this
    module aggregates on (`user_id` or, failing that, the name), which is what
    `player_links` is keyed by, so the caller can turn these into Slack @-mentions.
    Returns [] when there are no challenges today or everyone's played them all —
    the caller then sends nothing. Sorted case-insensitively by name for a stable
    message."""
    today_tokens = {c["token"] for c in data["challenges"] if c["date"] == today}
    if not today_tokens:
        return []
    start = week_start(date.fromisoformat(today))
    names: dict[str, str] = {}       # player key -> latest display name
    played: dict[str, set] = {}      # player key -> today's tokens they've scored
    for s in data["scores"]:
        if date.fromisoformat(s["date"]) >= start:
            key = s["user_id"] or s["name"]
            names[key] = s["name"]
            played.setdefault(key, set())
            if s["token"] in today_tokens:
                played[key].add(s["token"])
    return [
        {"key": k, "name": names[k]}
        for k in sorted(names, key=lambda k: names[k].lower())
        if len(played[k]) < len(today_tokens)
    ]


PODIUM = [4, 2, 1]  # points for a week's 1st, 2nd, 3rd


def season_leaderboard(data: dict | None = None, today: date | None = None) -> list[dict]:
    """Weekly ranking points summed across weeks: 1st=4, 2nd=2, 3rd=1.
    'points' counts every week incl. the current (provisional) one;
    'points_finished' counts only weeks that have already ended.
    Sorted by 'points_finished' (the stable rating) desc, tie-broken by live
    'points' — so the medal/rank column matches the table's default view.
    Returns [{'name', 'points', 'points_finished', 'weeks_played'}].

    Each week is ranked by the same weighted board as the weekly leaderboard.
    # ponytail: exact ties for a podium spot resolve by sort order (stable),
    # not shared points — weighted totals essentially never tie."""
    data = data if data is not None else _load()
    token_weight = _token_weight(data)
    current = week_start(today)

    weeks: dict[date, list[dict]] = {}  # week-Monday -> [scores]
    played: dict[str, set] = {}         # player key -> set of week-Mondays scored in
    names: dict[str, str] = {}          # player key -> latest display name
    for s in data["scores"]:
        wk = week_start(date.fromisoformat(s["date"]))
        weeks.setdefault(wk, []).append(s)
        key = s["user_id"] or s["name"]
        played.setdefault(key, set()).add(wk)
        names[key] = s["name"]

    agg: dict[str, dict] = {}           # player key -> {points, points_finished}
    for wk, scores in weeks.items():
        for i, r in enumerate(_weighted_board(scores, token_weight)[:3]):
            e = agg.setdefault(r["key"], {"points": 0, "points_finished": 0})
            e["points"] += PODIUM[i]
            if wk != current:
                e["points_finished"] += PODIUM[i]

    rows = []
    for key, wks in played.items():
        e = agg.get(key, {"points": 0, "points_finished": 0})
        rows.append(
            {
                "name": names[key],
                "points": e["points"],
                "points_finished": e["points_finished"],
                "weeks_played": len(wks),
            }
        )
    rows.sort(key=lambda r: (r["points_finished"], r["points"]), reverse=True)
    return rows


def all_time_leaderboard(data: dict | None = None) -> list[dict]:
    """Weighted board over every recorded score."""
    data = data if data is not None else _load()
    return _weighted_board(data["scores"], _token_weight(data))


def map_stats(data: dict | None = None) -> list[dict]:
    """Per-map raw-score stats: [{'map', 'games', 'avg', 'best'}].

    Challenges predating map tracking have no `map` — treat them as 'normal',
    the long-standing daily map. Averages use raw scores (single-map, so no
    cross-map weighting needed)."""
    data = data if data is not None else _load()
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


def player_stats(data: dict | None = None) -> list[dict]:
    """Per-player raw-score stats, sorted by games desc:
    [{'name', 'games', 'avg', 'best', 'pin',
      'avg_dist', 'perfects', 'chokes', 'avg_time'}].

    The guess-derived fields (avg_dist/perfects/chokes/avg_time) come from stored
    per-round `guesses`; rows predating guess capture contribute nothing to them.
    Per-map splits live in their own section — see map_player_stats."""
    data = data if data is not None else _load()
    by: dict[str, dict] = {}
    for s in data["scores"]:
        key = s["user_id"] or s["name"]
        p = by.setdefault(
            key,
            {
                "name": s["name"], "games": 0, "_total": 0, "best": 0,
                "pin": None, "_dist": 0.0, "_dist_n": 0, "_t": 0, "_t_n": 0,
                "perfects": 0, "chokes": 0,
            },
        )
        p["name"] = s["name"]
        p["games"] += 1
        p["_total"] += s["score"]
        p["best"] = max(p["best"], s["score"])
        p["pin"] = p["pin"] or s.get("pin")
        for g in s.get("guesses") or []:
            if g.get("pts") == 5000:
                p["perfects"] += 1
            if g.get("miss"):
                p["chokes"] += 1
            if g.get("dist") is not None:
                p["_dist"] += g["dist"]; p["_dist_n"] += 1
            if g.get("t") is not None:
                p["_t"] += g["t"]; p["_t_n"] += 1
    rows = []
    for p in sorted(by.values(), key=lambda p: p["games"], reverse=True):
        rows.append(
            {
                "name": p["name"],
                "games": p["games"],
                "avg": round(p["_total"] / p["games"]),
                "best": p["best"],
                "pin": p["pin"],
                "avg_dist": round(p["_dist"] / p["_dist_n"]) if p["_dist_n"] else 0,
                "perfects": p["perfects"],
                "chokes": p["chokes"],
                "avg_time": round(p["_t"] / p["_t_n"]) if p["_t_n"] else 0,
            }
        )
    return rows


def map_player_stats(data: dict | None = None) -> dict[str, list[dict]]:
    """Per-map player rankings:
    {map: [{'name','games','avg','best','avg_dist','avg_time','pin'}]}, each list
    sorted by avg score desc (best-first) so you can see who's strongest on each map.
    Distance/time average over rounds that recorded a `dist`/`t`; players with none
    show 0. Maps are keyed in alphabetical order."""
    data = data if data is not None else _load()
    token_map = {c["token"]: (c.get("map") or "normal") for c in data["challenges"]}
    by: dict[str, dict] = {}  # map -> playerkey -> agg
    for s in data["scores"]:
        m = token_map.get(s["token"], "normal")
        key = s["user_id"] or s["name"]
        p = by.setdefault(m, {}).setdefault(
            key,
            {"name": s["name"], "games": 0, "_total": 0, "best": 0,
             "pin": None, "_dist": 0.0, "_dist_n": 0, "_t": 0, "_t_n": 0},
        )
        p["name"] = s["name"]
        p["games"] += 1
        p["_total"] += s["score"]
        p["best"] = max(p["best"], s["score"])
        p["pin"] = p["pin"] or s.get("pin")
        for g in s.get("guesses") or []:
            if g.get("dist") is not None:
                p["_dist"] += g["dist"]; p["_dist_n"] += 1
            if g.get("t") is not None:
                p["_t"] += g["t"]; p["_t_n"] += 1
    out: dict[str, list[dict]] = {}
    for m in sorted(by):
        rows = [
            {
                "name": p["name"], "games": p["games"],
                "avg": round(p["_total"] / p["games"]),
                "best": p["best"],
                "avg_dist": round(p["_dist"] / p["_dist_n"]) if p["_dist_n"] else 0,
                "avg_time": round(p["_t"] / p["_t_n"]) if p["_t_n"] else 0,
                "pin": p["pin"],
            }
            for p in by[m].values()
        ]
        rows.sort(key=lambda r: r["avg"], reverse=True)
        out[m] = rows
    return out


def player_countries(data: dict | None = None, min_rounds: int = 2) -> list[dict]:
    """Each player's best & worst country by average round points, joining their
    per-round `guesses` to the round's actual-location country:
    [{'name', 'best_cc', 'best_avg', 'worst_cc', 'worst_avg', 'rounds'}].

    Only countries a player has seen >= `min_rounds` times qualify; players with
    none qualifying are omitted. `min_rounds` is the calibration knob — data is
    sparse now (few rounds per country), so keep it low and raise it as games pile up."""
    data = data if data is not None else _load()
    countries_by_token = {
        c["token"]: c.get("countries") or [] for c in data["challenges"]
    }
    by: dict[str, dict] = {}  # playerkey -> {name, cc -> [sum, n]}
    for s in data["scores"]:
        ccs = countries_by_token.get(s["token"], [])
        key = s["user_id"] or s["name"]
        p = by.setdefault(key, {"name": s["name"], "cc": {}})
        p["name"] = s["name"]
        for i, g in enumerate(s.get("guesses") or []):
            cc = ccs[i] if i < len(ccs) else None
            if not cc:
                continue
            acc = p["cc"].setdefault(cc, [0, 0])
            acc[0] += g.get("pts") or 0
            acc[1] += 1
    rows = []
    for p in by.values():
        avgs = {
            cc: (total / n, n)
            for cc, (total, n) in p["cc"].items()
            if n >= min_rounds
        }
        if not avgs:
            continue
        best = max(avgs, key=lambda cc: avgs[cc][0])
        worst = min(avgs, key=lambda cc: avgs[cc][0])
        rows.append(
            {
                "name": p["name"],
                "best_cc": best, "best_avg": round(avgs[best][0]),
                "worst_cc": worst, "worst_avg": round(avgs[worst][0]),
                "rounds": sum(n for _, n in p["cc"].values()),
            }
        )
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def round_wins(data: dict | None = None) -> list[dict]:
    """Per-round head-to-head, aggregated: how often each player had the strictly
    highest score on a round. [{'name', 'wins', 'rounds'}] sorted by wins desc.
    Ties for the top score on a round award nobody."""
    data = data if data is not None else _load()
    by_token: dict[str, list[dict]] = {}
    for s in data["scores"]:
        by_token.setdefault(s["token"], []).append(s)
    wins: dict[str, int] = {}
    rounds: dict[str, int] = {}
    names: dict[str, str] = {}
    for rows in by_token.values():
        # widest guess list decides how many rounds this challenge had
        n_rounds = max((len(r.get("guesses") or []) for r in rows), default=0)
        for i in range(n_rounds):
            contenders = []  # (key, pts)
            for r in rows:
                gs = r.get("guesses") or []
                if i < len(gs):
                    key = r["user_id"] or r["name"]
                    names[key] = r["name"]
                    rounds[key] = rounds.get(key, 0) + 1
                    contenders.append((key, gs[i].get("pts") or 0))
            if not contenders:
                continue
            top = max(pts for _, pts in contenders)
            leaders = [k for k, pts in contenders if pts == top]
            if len(leaders) == 1:
                wins[leaders[0]] = wins.get(leaders[0], 0) + 1
    rows = [
        {"name": names[k], "wins": wins.get(k, 0), "rounds": rounds[k]}
        for k in rounds
    ]
    rows.sort(key=lambda r: r["wins"], reverse=True)
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
                    {"token": "t2", "date": "2026-07-06", "url": "", "map": "fast", "weight": 1.75},
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
        assert ps["A"]["games"] == 2 and ps["A"]["best"] == 1000, ps
        # per-map rankings: normal has A (1000) above B (500); fast has only A
        mps = map_player_stats()
        assert [r["name"] for r in mps["normal"]] == ["A", "B"], mps
        assert mps["fast"][0]["avg"] == 1000 and len(mps["fast"]) == 1, mps

        # data= seam: functions accept an explicit dict (how the DB app feeds them);
        # weight is read per-challenge, not from any global map table.
        seam = {
            "challenges": [
                {"token": "x", "date": "2026-07-06", "url": "", "map": "a", "weight": 1.0},
                {"token": "y", "date": "2026-07-06", "url": "", "map": "b", "weight": 2.0},
            ],
            "scores": [
                {"date": "2026-07-06", "token": "x", "user_id": "p", "name": "P", "score": 100},
                {"date": "2026-07-06", "token": "y", "user_id": "p", "name": "P", "score": 100},
            ],
        }
        assert all_time_leaderboard(seam)[0]["total"] == 300, all_time_leaderboard(seam)  # 100*1 + 100*2

        # season points: two weeks; today in week of 2026-07-06 (that week is current)
        _save(
            {
                "challenges": [
                    {"token": "w1", "date": "2026-06-29", "url": "", "map": "normal"},
                    {"token": "w2", "date": "2026-07-06", "url": "", "map": "normal"},
                ],
                "scores": [
                    # finished week: A 1st, B 2nd, C 3rd
                    {"date": "2026-06-29", "token": "w1", "user_id": "a", "name": "A", "score": 1000},
                    {"date": "2026-06-29", "token": "w1", "user_id": "b", "name": "B", "score": 800},
                    {"date": "2026-06-29", "token": "w1", "user_id": "c", "name": "C", "score": 600},
                    # current week (provisional): B 1st, A 2nd
                    {"date": "2026-07-06", "token": "w2", "user_id": "b", "name": "B", "score": 1000},
                    {"date": "2026-07-06", "token": "w2", "user_id": "a", "name": "A", "score": 900},
                ],
            }
        )
        sb = {r["name"]: r for r in season_leaderboard(today=date(2026, 7, 8))}
        assert sb["A"]["points"] == 6 and sb["A"]["points_finished"] == 4, sb  # 4 + 2(prov)
        assert sb["B"]["points"] == 6 and sb["B"]["points_finished"] == 2, sb  # 2 + 4(prov)
        assert sb["C"]["points"] == 1 and sb["C"]["points_finished"] == 1, sb
        assert sb["A"]["weeks_played"] == 2 and sb["C"]["weeks_played"] == 1, sb

    # players_not_played_today: roster = anyone with a score this week; "played"
    # requires *every* challenge dated `today`. 2026-07-24 is a Fri (week Mon = 20).
    npt = {
        "challenges": [
            {"token": "d1", "date": "2026-07-24", "url": "", "map": "normal"},
            {"token": "d2", "date": "2026-07-24", "url": "", "map": "fast"},
            {"token": "e1", "date": "2026-07-21", "url": "", "map": "normal"},  # earlier this wk
        ],
        "scores": [
            {"date": "2026-07-24", "token": "d1", "user_id": "a", "name": "A", "score": 1},
            {"date": "2026-07-24", "token": "d2", "user_id": "a", "name": "A", "score": 1},  # A: both
            {"date": "2026-07-24", "token": "d1", "user_id": "b", "name": "B", "score": 1},  # B: 1 of 2
            {"date": "2026-07-21", "token": "e1", "user_id": "c", "name": "C", "score": 1},  # C: wk, not today
        ],
    }
    # returns key+name (the key is what player_links joins on, so @-mentions work)
    assert players_not_played_today(npt, "2026-07-24") == [
        {"key": "b", "name": "B"}, {"key": "c", "name": "C"}
    ], players_not_played_today(npt, "2026-07-24")
    assert players_not_played_today(npt, "2026-07-25") == []  # no challenges that day
    # a score with no GeoGuessr user_id keys on the name instead — same rule as the
    # boards, so a linked id-less player still resolves
    npt_anon = {
        "challenges": [
            {"token": "d1", "date": "2026-07-24", "url": "", "map": "normal"},
            {"token": "d2", "date": "2026-07-24", "url": "", "map": "fast"},
        ],
        "scores": [
            {"date": "2026-07-24", "token": "d1", "user_id": None, "name": "Nyx", "score": 1},
            {"date": "2026-07-24", "token": "d1", "user_id": "z", "name": "Zoe", "score": 1},
            {"date": "2026-07-24", "token": "d2", "user_id": "z", "name": "Zoe", "score": 1},
        ],
    }
    # Nyx played 1 of 2 and has no user_id -> keyed by name; Zoe played both -> absent
    assert players_not_played_today(npt_anon, "2026-07-24") == [{"key": "Nyx", "name": "Nyx"}], \
        players_not_played_today(npt_anon, "2026-07-24")

    # guess-derived stats: per-player aggregates, countries, round wins, and
    # graceful degradation on a legacy row that has no guesses/countries.
    with tempfile.TemporaryDirectory() as d:
        STORE_PATH = os.path.join(d, "store.json")

        def _g(pts, dist, t, miss=False):
            return {"pts": pts, "dist": dist, "t": t, "miss": miss}

        _save(
            {
                "challenges": [
                    {"token": "g1", "date": "2026-07-06", "url": "", "map": "normal",
                     "countries": ["us", "fr", "us", "fr", "de"]},
                    {"token": "g0", "date": "2026-07-06", "url": "", "map": "normal"},  # legacy
                ],
                "scores": [
                    {"date": "2026-07-06", "token": "g1", "user_id": "a", "name": "A", "score": 12000,
                     "pin": "http://x/a.png",
                     "guesses": [_g(5000, 0, 10), _g(1000, 500, 20), _g(4000, 100, 30),
                                 _g(2000, 300, 15), _g(0, 20000, 0, True)]},
                    {"date": "2026-07-06", "token": "g1", "user_id": "b", "name": "B", "score": 11000,
                     "guesses": [_g(4000, 50, 12), _g(3000, 200, 22), _g(3000, 150, 25),
                                 _g(1000, 400, 18), _g(0, 9000, 0, True)]},
                    {"date": "2026-07-06", "token": "g0", "user_id": "c", "name": "C", "score": 3000},  # no guesses
                ],
            }
        )
        ps = {p["name"]: p for p in player_stats()}
        assert ps["A"]["perfects"] == 1 and ps["A"]["chokes"] == 1, ps["A"]
        assert ps["A"]["avg_dist"] == round(20900 / 5) and ps["A"]["avg_time"] == 15, ps["A"]
        assert ps["A"]["pin"] == "http://x/a.png", ps["A"]
        # legacy row still aggregates; guess-derived fields are 0, no crash
        assert ps["C"]["games"] == 1 and ps["C"]["perfects"] == 0 and ps["C"]["avg_dist"] == 0, ps["C"]

        # per-map rankings carry per-map avg distance + time (A's 5 normal rounds)
        mps = {r["name"]: r for r in map_player_stats()["normal"]}
        assert mps["A"]["avg_dist"] == round(20900 / 5), mps["A"]
        assert mps["A"]["avg_time"] == 15, mps["A"]  # (10+20+30+15+0)/5
        assert mps["C"]["avg_dist"] == 0 and mps["C"]["avg_time"] == 0, mps["C"]  # legacy, no guesses

        pc = {r["name"]: r for r in player_countries()}  # min_rounds=2 -> us & fr qualify, de dropped
        assert pc["A"]["best_cc"] == "us" and pc["A"]["best_avg"] == 4500, pc["A"]
        assert pc["A"]["worst_cc"] == "fr" and pc["A"]["worst_avg"] == 1500, pc["A"]
        assert "C" not in pc, pc  # legacy row has no country data

        rw = {r["name"]: r for r in round_wins()}
        assert rw["A"]["wins"] == 3 and rw["B"]["wins"] == 1, rw  # r4 (0 vs 0) ties -> nobody
        assert rw["A"]["rounds"] == 5 and rw["B"]["rounds"] == 5, rw
        assert "C" not in rw, rw  # no per-round data
    print("store ok")
