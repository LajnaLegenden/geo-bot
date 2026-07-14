"""Server-rendered stats fragments. These builders are lifted verbatim from the
old web.py — the display logic was already good — and fed by store.py's stat
functions over one league's data (queries.load_league_data). htmx polls them.
"""
from __future__ import annotations

import html

from . import store

MEDALS = ["🥇", "🥈", "🥉"]

# GeoGuessr avatars: pin.url is a relative path served through their resize
# proxy; social-login avatars come back absolute.
PIN_BASE = "https://www.geoguessr.com/images/resize:auto:96:96/gravity:ce/plain/"


def _avatar_url(pin: str) -> str:
    return pin if pin.startswith("http") else PIN_BASE + pin


def _flag(cc: str) -> str:
    cc = (cc or "").lower()
    if len(cc) != 2 or not cc.isalpha():
        return cc.upper()
    return "".join(chr(0x1F1E6 + ord(c) - 97) for c in cc)


def _board_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['total']:,}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return ("<table><thead><tr><th>#</th><th>Player</th><th>Points</th>"
            f"<th>Games</th></tr></thead><tbody>{body}</tbody></table>")


def _season_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td><td>{r['points']}</td>"
        f"<td>{r['points_finished']}</td><td>{r['weeks_played']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return ("<table><thead><tr><th>#</th><th>Player</th>"
            "<th title='includes the ongoing (provisional) week'>Live</th>"
            "<th title='finished weeks only'>Stable</th>"
            f"<th>Weeks</th></tr></thead><tbody>{body}</tbody></table>")


def _maps_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No games yet.</p>"
    body = "".join(
        f"<tr><td>{html.escape(r['map'])}</td><td>{r['games']}</td>"
        f"<td>{r['avg']:,}</td><td>{r['best']:,}</td></tr>"
        for r in rows
    )
    return ("<table><thead><tr><th>Map</th><th>Games</th><th>Avg</th>"
            f"<th>Best</th></tr></thead><tbody>{body}</tbody></table>")


def _players_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No players yet.</p>"
    body = ""
    for r in rows:
        splits = ", ".join(
            f"{html.escape(m)} {v['avg']:,} avg ({v['games']})"
            for m, v in r["per_map"].items()
        )
        avatar = (
            f"<img src='{html.escape(_avatar_url(r['pin']))}' width='20' height='20' "
            f"style='vertical-align:middle;border-radius:50%;margin-right:.4rem' "
            f"onerror='this.style.display=&quot;none&quot;'>"
            if r.get("pin") else ""
        )
        body += (
            f"<tr><td>{avatar}{html.escape(r['name'])}</td><td>{r['games']}</td>"
            f"<td>{r['avg']:,}</td><td>{r['best']:,}</td>"
            f"<td>{round(r['avg_dist'] / 1000):,} km</td>"
            f"<td>{r['perfects']}</td><td>{r['chokes']}</td>"
            f"<td>{r['avg_time']}s</td>"
            f"<td class='per-map'>{splits}</td></tr>"
        )
    return ("<table><thead><tr><th>Player</th><th>Games</th><th>Avg</th><th>Best</th>"
            "<th title='avg distance off'>Dist off</th>"
            "<th title='5000-point rounds'>Perfects</th>"
            "<th title='timed-out / skipped rounds'>Chokes</th>"
            "<th title='avg time per round'>Avg time</th>"
            f"<th>Per map</th></tr></thead><tbody>{body}</tbody></table>")


def _countries_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No round data yet.</p>"
    body = "".join(
        f"<tr><td>{html.escape(r['name'])}</td>"
        f"<td>{_flag(r['best_cc'])} {r['best_cc'].upper()} ({r['best_avg']:,})</td>"
        f"<td>{_flag(r['worst_cc'])} {r['worst_cc'].upper()} ({r['worst_avg']:,})</td>"
        f"<td>{r['rounds']}</td></tr>"
        for r in rows
    )
    return ("<table><thead><tr><th>Player</th>"
            "<th title='highest avg round score'>Best</th>"
            "<th title='lowest avg round score'>Worst</th>"
            f"<th>Rounds</th></tr></thead><tbody>{body}</tbody></table>")


def _roundwins_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No round data yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['wins']}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return ("<table><thead><tr><th>#</th><th>Player</th>"
            "<th title='rounds where you had the top score'>Wins</th>"
            f"<th>Rounds</th></tr></thead><tbody>{body}</tbody></table>")


FRAGMENTS = {
    "weekly": lambda d: _board_html(store.weekly_leaderboard(d)),
    "season": lambda d: _season_html(store.season_leaderboard(d)),
    "alltime": lambda d: _board_html(store.all_time_leaderboard(d)),
    "maps": lambda d: _maps_html(store.map_stats(d)),
    "players": lambda d: _players_html(store.player_stats(d)),
    "countries": lambda d: _countries_html(store.player_countries(d)),
    "roundwins": lambda d: _roundwins_html(store.round_wins(d)),
}


def render(key: str, data: dict) -> str | None:
    fn = FRAGMENTS.get(key)
    return fn(data) if fn else None
