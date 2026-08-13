"""Slack message + variable builders and URL-explicit posters.

Incoming webhooks need no scopes — create one per channel at
https://api.slack.com/apps. The webhook/trigger URL is stored per league as an
encrypted credential and handed to post_to()/post_workflow_to() by the Slack
transport (geobot/transports/slack.py).
"""
from __future__ import annotations

import requests


def post_to(url: str, text: str, blocks: list | None = None) -> None:
    """Post to an explicit Incoming Webhook URL (multi-tenant: the URL comes
    from the league's stored credential, not an env var)."""
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    requests.post(url, json=payload, timeout=15).raise_for_status()


def post_workflow_to(url: str, variables: dict) -> None:
    """Post flat {title, body} to an explicit Workflow Builder trigger URL."""
    requests.post(url, json=variables, timeout=15).raise_for_status()


def cookie_expired_message() -> tuple[str, list]:
    text = "⚠️ GeoGuessr cookie expired — refresh the GEO_NCFA secret."
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":warning: *GeoGuessr cookie expired.*\n"
                    "The bot can't reach your account. Grab a fresh `_ncfa` cookie "
                    "and update the *GEO_NCFA* repo secret to get challenges going again."
                ),
            },
        }
    ]
    return text, blocks


_PLAY = "▶️ Play challenge"


def _play_button(url: str) -> dict:
    # A button with a `url` (and no action_id) is a link-button: it just opens
    # the URL, so it needs no interactivity endpoint / bot — works over an
    # incoming webhook.
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": _PLAY, "emoji": True},
        "url": url,
        "style": "primary",
    }


def challenge_message(url: str) -> tuple[str, list]:
    text = f":earth_africa: Today's GeoGuessr challenge is up! {url}"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":earth_africa: *Today's GeoGuessr challenge*\nScores count toward this week's board (resets Monday).",
            },
        },
        {"type": "actions", "elements": [_play_button(url)]},
    ]
    return text, blocks


def _leaderboard_lines(rows: list[dict], bold: bool = False) -> list[str]:
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(rows[:10]):
        rank = medals[i] if i < 3 else f"{i + 1}."
        name = f"*{r['name']}*" if bold else r["name"]
        lines.append(f"{rank} {name} — {r['total']:,} pts ({r['rounds']} games)")
    return lines


def _players_played(n: int) -> str:
    return f"{n} player{'' if n == 1 else 's'} played this week"


def leaderboard_message(
    rows: list[dict], stats_url: str | None = None, challenge_url: str | None = None
) -> tuple[str, list]:
    lines = _leaderboard_lines(rows, bold=True)
    body = "\n".join(lines) if lines else "_No scores yet this week._"
    text = "This week's leaderboard"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🏆 This week's leaderboard"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
    ]
    if rows:
        blocks.append(
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": _players_played(len(rows))},
            ]}
        )
    buttons = []
    if challenge_url:
        buttons.append(_play_button(challenge_url))
    if stats_url:
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "📊 Stats", "emoji": True},
            "url": stats_url,
        })
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    return text, blocks


def reminder_message(title: str, body: str, names: list[str]) -> tuple[str, list]:
    """Nudge naming players who still owe today's challenge(s). `title`/`body` are
    the league's UI-configured text; the names are appended to the body (plain
    text — GeoGuessr nicks, not Slack @mentions)."""
    people = ", ".join(names)
    text = f"{title} — {people}"
    full = f"{body}\n\n{people}" if body else people
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": full}},
    ]
    return text, blocks


_FALLBACK_URL = "https://www.geoguessr.com"


def _vars(title: str, body: str, button_text: str, button_url: str | None,
          players: str = "") -> dict:
    """Build a Workflow-Builder payload. All four message types share ONE trigger
    URL, and that trigger declares a fixed variable set — so every payload must
    carry every key, and the button (a URL-typed field) must always resolve to a
    real link. Omit a key, or leave button_url empty, and Slack fails the message
    step with "failed to start due to an invalid parameter" instead of just
    dropping the button. Hence the fallback: no natural link -> geoguessr.com.
    `players` is plain text, so "" is fine for the types that have no roster."""
    return {
        "title": title,
        "body": body,
        "players": players,
        "button_text": button_text,
        "button_url": button_url or _FALLBACK_URL,
    }


def challenge_variables(url: str) -> dict:
    return _vars(
        "🌍 Today's GeoGuessr challenge",
        "Scores count toward this week's board (resets Monday).",
        _PLAY, url,
    )


def leaderboard_variables(
    rows: list[dict], stats_url: str | None = None, challenge_url: str | None = None
) -> dict:
    # One button per message: the public stats page when it exists, else the
    # latest challenge (Block Kit gets both buttons — see leaderboard_message).
    text, url = ("📊 Stats", stats_url) if stats_url else (_PLAY, challenge_url)
    return _vars(
        "🏆 This week's leaderboard",
        "\n".join(_leaderboard_lines(rows)) if rows else "No scores yet this week.",
        text, url,
        players=_players_played(len(rows)) if rows else "No scores yet this week.",
    )


def reminder_variables(
    title: str, body: str, names: list[str], play_url: str | None = None
) -> dict:
    people = ", ".join(names)
    return _vars(
        title, f"{body}\n\n{people}" if body else people, _PLAY, play_url,
        players=people,
    )


def cookie_expired_variables() -> dict:
    return _vars(
        "⚠️ GeoGuessr cookie expired",
        "The bot can't reach your account. Grab a fresh _ncfa cookie and "
        "update the GEO_NCFA repo secret to get challenges going again.",
        "🔑 Get a fresh cookie", None,  # -> geoguessr.com, where you copy _ncfa
    )
