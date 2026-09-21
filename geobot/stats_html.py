"""Server-rendered stats fragments. These builders are lifted verbatim from the
old web.py — the display logic was already good — and fed by store.py's stat
functions over one league's data (queries.load_league_data). htmx polls them.
"""
from __future__ import annotations

import html
import json
from datetime import date, datetime

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


# 📈 Week progress: the eight categorical slots of the default data-viz palette,
# dark-surface steps, in the published order — that order is what keeps *adjacent*
# series separable for colorblind readers, so don't reshuffle it. Re-validated
# against this app's card surface (#1a1d29): worst adjacent ΔE 8.4 (CVD) / 19.3
# (normal vision), every slot ≥ 3:1 contrast. Past 8 players store.weekly_progress
# stops handing us series and counts the rest instead.
SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500",
                 "#d55181", "#008300", "#9085e9", "#e66767"]

# viewBox units; the card scales the whole thing to its own width.
CW, CH = 360, 190
PAD_L, PAD_R, PAD_T, PAD_B = 44, 10, 10, 22
PLOT_W, PLOT_H = CW - PAD_L - PAD_R, CH - PAD_T - PAD_B


def _kfmt(v: int) -> str:
    return f"{v / 1000:g}k" if v >= 1000 else str(v)


def _y_axis(top: int) -> tuple[int, int]:
    """(axis max, gridline step) for a 0-based axis: a round step that lands 2-5
    gridlines above zero and a max at or just past `top`."""
    if top < 1:
        return 1, 1
    mag = 10 ** (len(str(top)) - 1)
    for mult in (0.25, 0.5, 1, 2, 5):
        step = int(mag * mult) or 1
        if top / step <= 5:
            return step * -(-top // step), step
    return top, top


def _weekchart_html(prog: dict) -> str:
    """One running-total line per player across the displayed week. Inline SVG —
    no chart library, same server-rendered fragment deal as every other board.
    The key underneath names each player next to their swatch, so identity never
    rests on colour alone, and the 🏆 board beside it is the table view of the
    very same numbers (the last point of each line).

    weekchart.js turns the point columns into a crosshair + tooltip; everything
    it needs is markup it reads back off this SVG (`data-x`/`data-days` on the
    root, `data-day`/`data-name`/`data-value` per dot), so an htmx swap can't
    de-synchronise the two. Without JS the per-dot <title> is still the tooltip.

    `prog['days']` is read as a timestamp per point (a bare date parses as that
    day's midnight), and points sit at x proportional to real elapsed time
    between the first and last — two challenges 4h apart sit close together;
    a day with nothing posted leaves a real gap. The axis label below a point
    only repeats the date when it's the first point of a new day; same-day
    points after it just get their time, so multi-challenge days don't show
    the same weekday three times in a row."""
    days, players = prog["days"], prog["players"]
    if not players:
        return "<p>No scores yet.</p>"

    ymax, step = _y_axis(max(p["totals"][-1] for p in players))
    n = len(days)
    times = [datetime.fromisoformat(d) for d in days]
    titles = [t.strftime("%a %d %b %H:%M") for t in times]
    labels, prev_date = [], None
    for t in times:
        if t.date() != prev_date:
            labels.append(t.strftime("%a %d"))
            prev_date = t.date()
        else:
            labels.append(t.strftime("%H:%M"))

    span = (times[-1] - times[0]).total_seconds() if n > 1 else 0

    def x(i: int) -> float:
        if n <= 1:
            return round(PAD_L + PLOT_W / 2, 1)
        if span <= 0:  # degenerate: every point shares a timestamp
            return round(PAD_L + PLOT_W * i / (n - 1), 1)
        frac = (times[i] - times[0]).total_seconds() / span
        return round(PAD_L + PLOT_W * frac, 1)

    def y(v: int) -> float:
        return round(PAD_T + PLOT_H * (1 - v / ymax), 1)

    out = [
        "<div class='weekchart'>",
        f"<svg viewBox='0 0 {CW} {CH}' role='img' aria-label='Running weekly "
        "points per player' "
        f"data-x='{json.dumps([x(i) for i in range(n)])}' "
        f"data-days='{html.escape(json.dumps(titles))}'>",
    ]
    for v in range(0, ymax + 1, step):  # gridlines + their y labels
        out.append(
            f"<line class='grid' x1='{PAD_L}' y1='{y(v)}' x2='{CW - PAD_R}' y2='{y(v)}'/>"
            f"<text class='axis' x='{PAD_L - 6}' y='{y(v) + 3}' text-anchor='end'>"
            f"{_kfmt(v)}</text>"
        )
    for i, lab in enumerate(labels):  # day labels along the bottom
        out.append(
            f"<text class='axis' x='{x(i)}' y='{CH - 6}' text-anchor='middle'>{lab}</text>"
        )
    # The hover crosshair, parked at x=0 and hidden until weekchart.js moves it.
    # It sits under the series so a line is never cut in half by it.
    out.append(
        f"<line class='cross' x1='0' y1='{PAD_T}' x2='0' y2='{PAD_T + PLOT_H}'/>"
    )
    for s, p in enumerate(players):
        colour = SERIES_COLORS[s % len(SERIES_COLORS)]
        pts = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(p["totals"]))
        out.append(
            f"<polyline points='{pts}' fill='none' stroke='{colour}' stroke-width='2' "
            "stroke-linecap='round' stroke-linejoin='round'/>"
        )
        # A dot per day, ringed in the card colour so crossing lines stay readable.
        # The data-* trio is what the tooltip reads; the <title> is the no-JS
        # fallback, which weekchart.js strips once it takes over.
        for i, v in enumerate(p["totals"]):
            out.append(
                f"<circle cx='{x(i)}' cy='{y(v)}' r='3' fill='{colour}' "
                "stroke='var(--surface)' stroke-width='1.2' "
                f"data-day='{i}' data-name='{html.escape(p['name'])}' data-value='{v}'>"
                f"<title>{html.escape(p['name'])} · {titles[i]} · {v:,}</title></circle>"
            )
    out.append("</svg><div class='chart-tip' hidden></div><ul class='chart-key'>")
    for s, p in enumerate(players):
        out.append(
            f"<li><span class='swatch' style='background:"
            f"{SERIES_COLORS[s % len(SERIES_COLORS)]}'></span>"
            f"{html.escape(p['name'])} <b>{p['totals'][-1]:,}</b></li>"
        )
    out.append("</ul>")
    if prog["hidden"]:
        out.append(f"<p class='hint'>+{prog['hidden']} more not shown.</p>")
    out.append("</div>")
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
    "weekchart": lambda d, t: _weekchart_html(store.weekly_progress(d, t)),
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
    # week-progress chart: axis rounds up to a round step, one polyline + one
    # dot per challenge per player, and a key entry carrying the final total.
    assert _y_axis(45_000) == (50_000, 10_000) and _y_axis(3_000) == (3_000, 1_000)
    assert _y_axis(12_000) == (12_500, 2_500) and _y_axis(0) == (1, 1)
    wc = _weekchart_html({
        "days": ["2026-07-20", "2026-07-21", "2026-07-22"],
        "players": [{"name": "A <b>", "totals": [1000, 1000, 3000]},
                    {"name": "B", "totals": [0, 500, 900]}],
        "hidden": 2,
    })
    assert wc.count("<polyline") == 2 and wc.count("<circle") == 6, wc
    assert "A &lt;b&gt;" in wc and "<b>3,000</b>" in wc, wc   # escaped name, final total
    assert SERIES_COLORS[1] in wc and ">Mon 20<" in wc and ">Wed 22<" in wc, wc
    assert "+2 more not shown." in wc, wc
    # the hover layer's contract with weekchart.js: x-positions + labels on the
    # root, a parked crosshair, an empty tooltip box, and a data trio per dot.
    # A bare date reads as that day's midnight, and 3 days apart evenly (24h
    # each) still lands on the old evenly-spaced positions.
    assert "data-x='[44.0, 197.0, 350.0]'" in wc and "Mon 20 Jul 00:00" in wc, wc
    assert "<line class='cross'" in wc and "<div class='chart-tip' hidden>" in wc, wc
    assert wc.count("data-day=") == 6 and "data-value='3000'" in wc, wc

    # two challenges the same day (10:00 and 14:00) sit proportionally 4h apart
    # in a 24h span (1/6 of the plot width), not merged into one day-point; the
    # second axis label drops the repeated date and shows just the time.
    wc2 = _weekchart_html({
        "days": ["2026-07-20T10:00:00", "2026-07-20T14:00:00", "2026-07-21T10:00:00"],
        "players": [{"name": "A", "totals": [1000, 1500, 1500]}],
        "hidden": 0,
    })
    assert ">Mon 20<" in wc2 and ">14:00<" in wc2 and ">Tue 21<" in wc2, wc2
    assert "data-x='[44.0, 95.0, 350.0]'" in wc2, wc2
    assert "Mon 20 Jul 14:00" in wc2, wc2
    assert _weekchart_html({"days": [], "players": [], "hidden": 0}) == "<p>No scores yet.</p>"

    print("stats_html ok")
