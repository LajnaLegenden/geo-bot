"""Stats: private fragments behind login (owner-scoped) and a public read-only
page at /s/<slug>. Public routes resolve the slug and 404 unless the league
opted into a public slug, so private leagues never leak.

`?season=<id>` narrows every board to one season (see queries.season_window).
Absent, it means the live season; present but not this league's, it 404s — same
isolation rule as every other owned-resource read.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, render_template, request, session

from .. import db, queries, stats_html
from ..security import login_required

bp = Blueprint("stats", __name__)


def season_context(conn, league_id) -> tuple[list, object, bool]:
    """(seasons, selected, is_current) for one league, honouring ?season=<id>.
    Shared with leagues.detail so the page header and its fragments agree."""
    current = queries.current_season(conn, league_id)
    selected = current
    sid = request.args.get("season", type=int)
    if sid:
        selected = queries.get_season(conn, sid, league_id)
        if selected is None:
            abort(404)
    is_current = selected is None or (current is not None
                                     and selected["id"] == current["id"])
    return queries.list_seasons(conn, league_id), selected, is_current


def _week_today(data: dict, is_current: bool) -> date | None:
    """None = the real current week (the live season's normal behaviour). For a
    season that isn't live, the latest date it recorded, so 🏆 shows that season's
    final week instead of an empty current one. None again when it recorded
    nothing (a future-dated season) — the normal empty state is right there."""
    if is_current:
        return None
    dates = [s["date"] for s in data["scores"]]
    return date.fromisoformat(max(dates)) if dates else None


def _fragment(league_id: int, key: str) -> str:
    conn = db.conn()
    _, selected, is_current = season_context(conn, league_id)
    since = until = None
    if selected is not None and key != "alltime":
        # 👑 All-time is the one board that stays all-history, by design.
        since, until = queries.season_window(conn, selected["id"], league_id)
    data = queries.load_league_data(conn, league_id, since, until)
    out = stats_html.render(key, data, _week_today(data, is_current))
    if out is None:
        abort(404)
    return out


@bp.get("/leagues/<int:league_id>/fragment/<key>")
@login_required
def private_fragment(league_id, key):
    if not queries.get_league(db.conn(), league_id, session["uid"]):
        abort(404)
    return _fragment(league_id, key)


@bp.get("/s/<slug>")
def public(slug):
    league = queries.get_league_by_slug(db.conn(), slug)
    if not league:
        abort(404)
    seasons, selected, is_current = season_context(db.conn(), league["id"])
    return render_template("public_stats.html", league=league, slug=slug,
                           seasons=seasons, season=selected, is_current=is_current)


@bp.get("/s/<slug>/fragment/<key>")
def public_fragment(slug, key):
    league = queries.get_league_by_slug(db.conn(), slug)
    if not league:
        abort(404)
    return _fragment(league["id"], key)
