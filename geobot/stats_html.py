"""Server-rendered stats fragments. These builders are lifted verbatim from the
old web.py — the display logic was already good — and fed by store.py's stat
functions over one league's data (queries.load_league_data). htmx polls them.
"""
from __future__ import annotations

import html
from datetime import date

from . import store

MEDALS = ["🥇", "🥈", "🥉"]

# GeoGuessr avatars: pin.url is a relative path served through their resize
# proxy; social-login avatars come back absolute.
PIN_BASE = "https://www.geoguessr.com/images/resize:auto:96:96/gravity:ce/plain/"


def _avatar_url(pin: str) -> str:
    return pin if pin.startswith("http") else PIN_BASE + pin


def _avatar_img(pin: str | None) -> str:
    """Inline round avatar that hides itself if the image 404s. Empty when no pin."""
    if not pin:
        return ""
    return (
        f"<img src='{html.escape(_avatar_url(pin))}' width='20' height='20' "
        f"style='vertical-align:middle;border-radius:50%;margin-right:.4rem' "
        f"onerror='this.style.display=&quot;none&quot;'>"
    )


def _flag(cc: str) -> str:
    cc = (cc or "").lower()
    if len(cc) != 2 or not cc.isalpha():
        return cc.upper()
    return "".join(chr(0x1F1E6 + ord(c) - 97) for c in cc)


def _rank_cells(values: list) -> list[str]:
    """Standard competition ranking ('1224'): equal values share a rank and the
    next distinct value skips the tied positions — so a tie for 1st yields two
    🥇 and the following player is 3rd. Rows must already be sorted best-first.
    Returns the display cell per row (medal for ranks 1-3, else 'N.')."""
    cells, rank = [], 0
    for i, v in enumerate(values):
        if i == 0 or v != values[i - 1]:
            rank = i + 1
        cells.append(MEDALS[rank - 1] if rank <= 3 else f"{rank}.")
    return cells


def _board_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    ranks = _rank_cells([r["total"] for r in rows])
    body = "".join(
        f"<tr><td>{ranks[i]}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['total']:,}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return ("<table><thead><tr><th>#</th><th>Player</th><th>Points</th>"
            f"<th>Games</th></tr></thead><tbody>{body}</tbody></table>")


def _challenges_html(rows: list[dict]) -> str:
    """The week's challenges grouped under a day heading, newest day first, each
    with its winner and who skipped it. Rows arrive pre-sorted (day desc, game
    asc) and that grouping *is* the order, so the board takes no default sort
    (`none, none` in STAT_SECTIONS). A click still sorts, but only within one
    day's own table, so the day headings stay correct either way."""
    if not rows:
        return "<p>No challenges this week.</p>"
    out, day = ["<div class='challenges'>"], None
    for r in rows:
        if r["date"] != day:
            if day is not None:
                out.append("</tbody></table>")
            day = r["date"]
            out.append(
                f"<h3>{html.escape(date.fromisoformat(day).strftime('%a %d %b'))}</h3>"
                "<table><thead><tr><th>Game</th><th>Winner</th>"
                "<th title='finished it, out of this week&#39;s players'>Played</th>"
                "<th>Not played</th></tr></thead><tbody>"
            )
        name = html.escape(r["map"])
        game = (
            f"<a href='{html.escape(r['url'])}' target='_blank' rel='noopener'>{name}</a>"
            if r["url"] else name
        )
        winner = (
            f"{_avatar_img(r['winner_pin'])}{html.escape(r['winner'])} "
            f"{r['winner_score']:,}"
            if r["winner"] else "—"
        )
        missing = ", ".join(html.escape(n) for n in r["missing"]) or "—"
        out.append(
            f"<tr><td>{game}</td><td>{winner}</td>"
            f"<td>{r['played']}/{r['roster']}</td><td>{missing}</td></tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def _season_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    ranks = _rank_cells([r["points_finished"] for r in rows])
    body = "".join(
        f"<tr><td>{ranks[i]}</td>"
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
        avatar = _avatar_img(r.get("pin"))
        body += (
            f"<tr><td>{avatar}{html.escape(r['name'])}</td><td>{r['games']}</td>"
            f"<td>{r['avg']:,}</td><td>{r['best']:,}</td>"
            f"<td>{round(r['avg_dist'] / 1000):,} km</td>"
            f"<td>{r['perfects']}</td><td>{r['chokes']}</td>"
            f"<td>{r['avg_time']}s</td></tr>"
        )
    return ("<table><thead><tr><th>Player</th><th>Games</th><th>Avg</th><th>Best</th>"
            "<th title='avg distance off'>Dist off</th>"
            "<th title='5000-point rounds'>Perfects</th>"
            "<th title='timed-out / skipped rounds'>Chokes</th>"
            "<th title='avg time per round'>Avg time</th>"
            f"</tr></thead><tbody>{body}</tbody></table>")


def _map_players_html(maps: dict[str, list[dict]]) -> str:
    """One ranked player table per map, best-avg-first, so you can read who's
    strongest where. Same columns as the Maps summary (Games/Avg/Best) plus the
    Players table's Dist-off and Avg-time."""
    if not maps:
        return "<p>No games yet.</p>"
    out = []
    for m, rows in maps.items():
        ranks = _rank_cells([r["avg"] for r in rows])
        body = "".join(
            f"<tr><td>{ranks[i]}</td>"
            f"<td>{_avatar_img(r.get('pin'))}{html.escape(r['name'])}</td>"
            f"<td>{r['games']}</td><td>{r['avg']:,}</td><td>{r['best']:,}</td>"
            f"<td>{round(r['avg_dist'] / 1000):,} km</td>"
            f"<td>{r['avg_time']}s</td></tr>"
            for i, r in enumerate(rows)
        )
        out.append(
            f"<h3>{html.escape(m)}</h3>"
            "<table><thead><tr><th>#</th><th>Player</th><th>Games</th>"
            "<th>Avg</th><th>Best</th>"
            "<th title='avg distance off'>Dist off</th>"
            "<th title='avg time per round'>Avg time</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    return "".join(out)


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
    ranks = _rank_cells([r["wins"] for r in rows])
    body = "".join(
        f"<tr><td>{ranks[i]}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['wins']}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return ("<table><thead><tr><th>#</th><th>Player</th>"
            "<th title='rounds where you had the top score'>Wins</th>"
            f"<th>Rounds</th></tr></thead><tbody>{body}</tbody></table>")


# (data, week_today) -> html. Only the week-scoped boards care about
# `week_today`; the rest are already scoped by whatever window `data` was
# loaded with.
FRAGMENTS = {
    "weekly": lambda d, t: _board_html(store.weekly_leaderboard(d, t)),
    "challenges": lambda d, t: _challenges_html(store.weekly_challenges(d, t)),
    "season": lambda d, t: _season_html(store.season_leaderboard(d)),
    "alltime": lambda d, t: _board_html(store.all_time_leaderboard(d)),
    "maps": lambda d, t: _maps_html(store.map_stats(d)),
    "mapplayers": lambda d, t: _map_players_html(store.map_player_stats(d)),
    "players": lambda d, t: _players_html(store.player_stats(d)),
    "countries": lambda d, t: _countries_html(store.player_countries(d)),
    "roundwins": lambda d, t: _roundwins_html(store.round_wins(d)),
}


def render(key: str, data: dict, week_today=None) -> str | None:
    fn = FRAGMENTS.get(key)
    return fn(data, week_today) if fn else None


if __name__ == "__main__":  # python -m geobot.stats_html — self-check
    assert _rank_cells([10, 10, 8, 5]) == ["🥇", "🥇", "🥉", "4."]      # tie for 1st -> next is 3rd
    assert _rank_cells([10, 8, 8, 8, 5]) == ["🥇", "🥈", "🥈", "🥈", "5."]  # 3-way tie for 2nd
    assert _rank_cells([5, 4, 3]) == ["🥇", "🥈", "🥉"]
    assert _rank_cells([]) == []

    # challenges board: one <h3> + table per day, in the order the rows arrive
    ch = _challenges_html([
        {"date": "2026-07-24", "map": "fast", "url": "http://c/f1", "winner": "A, B",
         "winner_score": 5000, "winner_pin": None, "played": 2, "roster": 3,
         "missing": ["C"]},
        {"date": "2026-07-22", "map": "normal", "url": "", "winner": "",
         "winner_score": 0, "winner_pin": None, "played": 0, "roster": 3,
         "missing": ["A", "B", "C"]},
    ])
    assert ch.count("<h3>") == 2 and ch.count("<table>") == 2, ch
    assert "Mon 20 Jul" not in ch and "Fri 24 Jul" in ch, ch
    assert "<a href='http://c/f1'" in ch, ch          # play link when a url exists
    assert ">normal</td>" in ch or ">normal<" in ch, ch  # plain text when it doesn't
    assert "<td>2/3</td>" in ch and "<td>0/3</td>" in ch, ch
    assert "A, B, C" in ch, ch                        # everyone missing, unplayed day
    assert _challenges_html([]) == "<p>No challenges this week.</p>"
    print("stats_html ok")
