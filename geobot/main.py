"""Entry point. Two modes:

  python -m geobot.main new <map>  # create today's challenge for <map> + post link
  python -m geobot.main update     # refresh scores for last 7 days + post leaderboard

Run `new` in the morning and `update` in the evening (two cron schedules),
or run `update` right before `new` the next day — whatever you prefer.
Map configs live in geobot/maps.py.
"""
from __future__ import annotations

import os
import sys

from . import maps, slack, store
from .geoguessr import GeoGuessr


def _client() -> GeoGuessr:
    return GeoGuessr(os.environ["GEO_NCFA"])


def _sink() -> str:
    return os.environ.get("SLACK_SINK", "incoming")


def _emit_challenge(url: str) -> None:
    if _sink() == "workflow":
        slack.post_workflow(slack.challenge_variables(url))
    else:
        slack.post(*slack.challenge_message(url))


def _emit_leaderboard(rows: list[dict]) -> None:
    if _sink() == "workflow":
        slack.post_workflow(slack.leaderboard_variables(rows))
    else:
        slack.post(*slack.leaderboard_message(rows))


def _emit_cookie_expired() -> None:
    if _sink() == "workflow":
        slack.post_workflow(slack.cookie_expired_variables())
    else:
        slack.post(*slack.cookie_expired_message())


def _ensure_auth(gg: GeoGuessr) -> bool:
    """Verify the cookie; alert Slack and signal failure if it's dead."""
    if gg.check_auth():
        return True
    _emit_cookie_expired()
    print("Auth check failed: GEO_NCFA cookie is invalid.", file=sys.stderr)
    return False


def cmd_new(map_name: str) -> None:
    if map_name not in maps.MAPS:
        print(
            f"unknown map: {map_name} (have: {', '.join(maps.MAPS)})",
            file=sys.stderr,
        )
        sys.exit(1)
    gg = _client()
    if not _ensure_auth(gg):
        sys.exit(1)
    token = gg.create_challenge(**maps.create_kwargs(map_name))
    url = gg.challenge_url(token)
    store.add_challenge(token, url, map_name)
    _emit_challenge(url)
    print(f"Created challenge {token} ({map_name})")


def cmd_update() -> None:
    gg = _client()
    if not _ensure_auth(gg):
        sys.exit(1)
    for token in store.recent_tokens(days=7):
        try:
            scores = gg.highscores(token)
            store.upsert_scores(token, scores)
            print(f"Updated {token}: {len(scores)} scores")
        except Exception as e:  # keep going if one token fails
            print(f"Skip {token}: {e}", file=sys.stderr)
    rows = store.weekly_leaderboard()
    _emit_leaderboard(rows)


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["new"] and len(args) >= 2:
        cmd_new(args[1])
    elif args == ["update"]:
        cmd_update()
    else:
        print("usage: python -m geobot.main new <map> | update", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
