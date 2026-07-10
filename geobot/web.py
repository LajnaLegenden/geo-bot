"""Tiny stdlib web server for the stats site.

Reads store.json *server-side* and serves only computed stats as HTML fragments
(htmx polls them). The raw store, `data/`, `.git` and source files are never
served — only the handful of routes below respond, everything else is 404.

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
  table { border-collapse: collapse; width: 100%; font-size: .9rem; }
  th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #8884; }
  th { font-weight: 600; }
  td:nth-child(n+3), th:nth-child(n+3) { text-align: right; }
  .per-map { text-align: left; color: #8889; font-size: .8rem; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<h1>🌍 GeoGuessr stats</h1>
<div class="grid">
  <section><h2>🏆 This week</h2>
    <div hx-get="/fragment/weekly" hx-trigger="load, every 60s">…</div></section>
  <section><h2>👑 All-time</h2>
    <div hx-get="/fragment/alltime" hx-trigger="load, every 60s">…</div></section>
  <section><h2>🗺️ Maps</h2>
    <div hx-get="/fragment/maps" hx-trigger="load, every 60s">…</div></section>
  <section><h2>🧑 Players</h2>
    <div hx-get="/fragment/players" hx-trigger="load, every 60s">…</div></section>
</div>
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


def _players_html(rows: list[dict]) -> str:
    if not rows:
        return "<p>No players yet.</p>"
    body = ""
    for r in rows:
        splits = ", ".join(
            f"{html.escape(m)} {v['avg']:,} avg ({v['games']})"
            for m, v in r["per_map"].items()
        )
        body += (
            f"<tr><td>{html.escape(r['name'])}</td><td>{r['games']}</td>"
            f"<td>{r['avg']:,}</td><td>{r['best']:,}</td>"
            f"<td class='per-map'>{splits}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Player</th><th>Games</th><th>Avg</th>"
        f"<th>Best</th><th>Per map</th></tr></thead><tbody>{body}</tbody></table>"
    )


FRAGMENTS = {
    "/fragment/weekly": lambda: _board_html(store.weekly_leaderboard()),
    "/fragment/alltime": lambda: _board_html(store.all_time_leaderboard()),
    "/fragment/maps": lambda: _maps_html(store.map_stats()),
    "/fragment/players": lambda: _players_html(store.player_stats()),
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
