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


def _play_button(url: str) -> dict:
    # A button with a `url` (and no action_id) is a link-button: it just opens
    # the URL, so it needs no interactivity endpoint / bot — works over an
    # incoming webhook.
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "▶️ Play challenge", "emoji": True},
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


def challenge_variables(url: str) -> dict:
    # Workflow Builder path: the URL + its label are standalone variables so the
    # workflow can bind them to a message button (Block Kit buttons only exist on
    # the incoming-webhook path). One button per message, so both this and the
    # leaderboard use the same variable names — a challenge post fills them with
    # the challenge link, a leaderboard post with the stats link.
    return {
        "title": "🌍 Today's GeoGuessr challenge",
        "body": "Scores count toward this week's board (resets Monday).",
        "button_text": "▶️ Play challenge",
        "button_url": url,
    }


def leaderboard_variables(rows: list[dict], stats_url: str | None = None) -> dict:
    v = {
        "title": "🏆 This week's leaderboard",
        "body": "\n".join(_leaderboard_lines(rows)) if rows else "No scores yet this week.",
        "players": _players_played(len(rows)) if rows else "No scores yet this week.",
    }
    if stats_url:  # single button on the leaderboard -> the public stats page
        v["button_text"] = "📊 Stats"
        v["button_url"] = stats_url
    return v


def reminder_variables(title: str, body: str, names: list[str]) -> dict:
    people = ", ".join(names)
    return {
        "title": title,
        "body": f"{body}\n\n{people}" if body else people,
        "players": people,
    }


def cookie_expired_variables() -> dict:
    return {
        "title": "⚠️ GeoGuessr cookie expired",
        "body": (
            "The bot can't reach your account. Grab a fresh _ncfa cookie and "
            "update the GEO_NCFA repo secret to get challenges going again."
        ),
    }
