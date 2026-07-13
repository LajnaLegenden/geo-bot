"""Tiny stdlib web server for the stats site.

Reads store.json *server-side* and serves only computed stats as HTML fragments
(htmx polls them). The raw store, `data/`, `.git` and source files are never
served — only the handful of routes below respond, everything else is 404.

One exception to "no external resources": player avatar `<img>` tags point at
GeoGuessr's CDN, so the browser fetches those images directly from GeoGuessr.

Run: `python -m geobot.web` (binds 0.0.0.0:$PORT, default 8080).
"""
from __future__ import annotations

import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store

PORT = int(os.environ.get("PORT", "8080"))
HTMX_PATH = os.path.join(os.path.dirname(__file__), "..", "web", "htmx.min.js")
MEDALS = ["🥇", "🥈", "🥉"]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoGuessr stats</title>
<script src="/htmx.min.js"></script>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto;
         padding: 0 1rem; line-height: 1.4; }
  h1 { margin-bottom: 1.5rem; }
  h2 { margin: 0 0 .5rem; font-size: 1.1rem; }
  .grid { display: grid; gap: 1.5rem; grid-template-columns: 1fr 1fr; }
  section { min-width: 0; }
  .wide { grid-column: 1 / -1; }  /* full-width row for the many-column Players table */
  table { border-collapse: collapse; width: 100%; font-size: .9rem; }
  th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #8884; }
  th { font-weight: 600; cursor: pointer; user-select: none; }
  td:nth-child(n+3), th:nth-child(n+3) { text-align: right; }
  .per-map { text-align: left; color: #8889; font-size: .8rem; }
  .hint { color: #8889; font-size: .8rem; margin: -.25rem 0 .5rem; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<h1>🌍 GeoGuessr stats</h1>
<div class="grid">
  <section><h2>🏆 This week</h2>
    <div hx-get="/fragment/weekly" hx-trigger="load, every 60s">…</div></section>
  <section><h2>🏅 Season points</h2>
    <p class="hint">Weekly podium points (1st = 4, 2nd = 2, 3rd = 1) summed across weeks ·
      Live counts the ongoing week, Stable is finished weeks only</p>
    <div hx-get="/fragment/season" hx-trigger="load, every 60s">…</div></section>
  <section><h2>👑 All-time</h2>
    <div hx-get="/fragment/alltime" hx-trigger="load, every 60s">…</div></section>
  <section><h2>🗺️ Maps</h2>
    <div hx-get="/fragment/maps" hx-trigger="load, every 60s">…</div></section>
  <section class="wide"><h2>🧑 Players</h2>
    <p class="hint">Dist off = avg distance from the right spot · Perfects = 5000-pt rounds ·
      Chokes = timed-out / skipped rounds · Avg time = seconds per round</p>
    <div hx-get="/fragment/players" hx-trigger="load, every 60s">…</div></section>
  <section><h2>🌍 Best / worst countries</h2>
    <p class="hint">Each player's strongest &amp; weakest country by average round score
      (min 2 rounds seen there)</p>
    <div hx-get="/fragment/countries" hx-trigger="load, every 60s">…</div></section>
  <section><h2>⚔️ Round wins</h2>
    <p class="hint">Rounds where you outscored everyone else who played that challenge</p>
    <div hx-get="/fragment/roundwins" hx-trigger="load, every 60s">…</div></section>
</div>
<script>
// Click any column header to sort its table. Re-applies after each htmx poll
// (which replaces the table) so the chosen sort survives the 60s refresh.
(function () {
  function num(s) { var n = parseFloat(s.replace(/[^0-9.\\-]/g, "")); return (/\\d/.test(s) && !isNaN(n)) ? n : null; }
  function sort(table, col, dir) {
    var tb = table.tBodies[0]; if (!tb) return;
    [].slice.call(tb.rows).sort(function (a, b) {
      var x = a.cells[col].textContent.trim(), y = b.cells[col].textContent.trim();
      var nx = num(x), ny = num(y), r = (nx !== null && ny !== null) ? nx - ny : x.localeCompare(y);
      return dir < 0 ? -r : r;
    }).forEach(function (row) { tb.appendChild(row); });
    var ths = table.tHead.rows[0].cells;
    for (var i = 0; i < ths.length; i++) {
      var base = ths[i].dataset.label || (ths[i].dataset.label = ths[i].textContent);
      ths[i].textContent = base + (i === col ? (dir < 0 ? " ▼" : " ▲") : "");
    }
  }
  document.addEventListener("click", function (e) {
    var th = e.target.closest("th"); if (!th) return;
    var table = th.closest("table"), box = th.closest("[hx-get]"); if (!table || !box) return;
    var col = [].indexOf.call(th.parentNode.cells, th);
    var dir = (box.dataset.sortCol == col && box.dataset.sortDir == "1") ? -1 : 1;
    box.dataset.sortCol = col; box.dataset.sortDir = dir > 0 ? "1" : "-1";
    sort(table, col, dir);
  });
  document.body.addEventListener("htmx:afterSettle", function (e) {
    var box = e.target; if (box.dataset.sortCol == null) return;
    var table = box.querySelector("table"); if (table) sort(table, +box.dataset.sortCol, box.dataset.sortDir == "-1" ? -1 : 1);
  });
})();
</script>
</body>
</html>"""


def _board_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['total']:,}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return (
        "<table><thead><tr><th>#</th><th>Player</th><th>Points</th>"
        f"<th>Games</th></tr></thead><tbody>{body}</tbody></table>"
    )


def _season_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No scores yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['points']}</td>"
        f"<td>{r['points_finished']}</td>"
        f"<td>{r['weeks_played']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return (
        "<table><thead><tr><th>#</th><th>Player</th>"
        "<th title='includes the ongoing (provisional) week'>Live</th>"
        "<th title='finished weeks only'>Stable</th>"
        f"<th>Weeks</th></tr></thead><tbody>{body}</tbody></table>"
    )


def _maps_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No games yet.</p>"
    body = "".join(
        f"<tr><td>{html.escape(r['map'])}</td><td>{r['games']}</td>"
        f"<td>{r['avg']:,}</td><td>{r['best']:,}</td></tr>"
        for r in rows
    )
    return (
        "<table><thead><tr><th>Map</th><th>Games</th><th>Avg</th>"
        f"<th>Best</th></tr></thead><tbody>{body}</tbody></table>"
    )


# GeoGuessr avatars: pin.url is a relative path (e.g. "pin/<hash>.png") served
# through their image-resize proxy. Social-login avatars come back absolute.
PIN_BASE = "https://www.geoguessr.com/images/resize:auto:96:96/gravity:ce/plain/"


def _avatar_url(pin: str) -> str:
    return pin if pin.startswith("http") else PIN_BASE + pin


def _flag(cc: str) -> str:
    """ISO-3166 alpha-2 country code -> flag emoji (regional-indicator letters).
    Falls back to the uppercased code for anything that isn't 2 letters."""
    cc = (cc or "").lower()
    if len(cc) != 2 or not cc.isalpha():
        return cc.upper()
    return "".join(chr(0x1F1E6 + ord(c) - 97) for c in cc)


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
    return (
        "<table><thead><tr><th>Player</th><th>Games</th><th>Avg</th><th>Best</th>"
        "<th title='avg distance off'>Dist off</th>"
        "<th title='5000-point rounds'>Perfects</th>"
        "<th title='timed-out / skipped rounds'>Chokes</th>"
        "<th title='avg time per round'>Avg time</th>"
        f"<th>Per map</th></tr></thead><tbody>{body}</tbody></table>"
    )


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
    return (
        "<table><thead><tr><th>Player</th>"
        "<th title='highest avg round score'>Best</th>"
        "<th title='lowest avg round score'>Worst</th>"
        f"<th>Rounds</th></tr></thead><tbody>{body}</tbody></table>"
    )


def _roundwins_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No round data yet.</p>"
    body = "".join(
        f"<tr><td>{MEDALS[i] if i < 3 else f'{i + 1}.'}</td>"
        f"<td>{html.escape(r['name'])}</td>"
        f"<td>{r['wins']}</td><td>{r['rounds']}</td></tr>"
        for i, r in enumerate(rows)
    )
    return (
        "<table><thead><tr><th>#</th><th>Player</th>"
        "<th title='rounds where you had the top score'>Wins</th>"
        f"<th>Rounds</th></tr></thead><tbody>{body}</tbody></table>"
    )


FRAGMENTS = {
    "/fragment/weekly": lambda: _board_html(store.weekly_leaderboard()),
    "/fragment/season": lambda: _season_html(store.season_leaderboard()),
    "/fragment/alltime": lambda: _board_html(store.all_time_leaderboard()),
    "/fragment/maps": lambda: _maps_html(store.map_stats()),
    "/fragment/players": lambda: _players_html(store.player_stats()),
    "/fragment/countries": lambda: _countries_html(store.player_countries()),
    "/fragment/roundwins": lambda: _roundwins_html(store.round_wins()),
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype: str = "text/html; charset=utf-8", code: int = 200):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(PAGE)
        if path == "/htmx.min.js":
            try:
                with open(HTMX_PATH, "rb") as f:
                    return self._send(f.read(), "application/javascript")
            except OSError:
                return self._send("not found", "text/plain", 404)
        if path in FRAGMENTS:
            try:
                return self._send(FRAGMENTS[path]())
            except Exception as e:  # a bad store shouldn't take the server down
                return self._send(f"<p>error: {html.escape(str(e))}</p>", code=500)
        self._send("not found", "text/plain", 404)

    def log_message(self, *args):  # keep container logs quiet
        pass


def main() -> None:
    print(f"serving stats on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
