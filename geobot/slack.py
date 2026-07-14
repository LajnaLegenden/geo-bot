"""Post to Slack via an Incoming Webhook (simplest) or a bot token.

Incoming webhook needs no scopes — just create one for your channel at
https://api.slack.com/apps and set SLACK_WEBHOOK_URL.
"""
from __future__ import annotations

import os

import requests


def post(text: str, blocks: list | None = None) -> None:
    url = os.environ["SLACK_WEBHOOK_URL"]
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()


def post_workflow(variables: dict) -> None:
    """POST flat {title, body} to a Workflow Builder 'From a webhook' trigger."""
    url = os.environ["SLACK_WORKFLOW_URL"]
    r = requests.post(url, json=variables, timeout=15)
    r.raise_for_status()


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


def challenge_message(url: str) -> tuple[str, list]:
    text = f":earth_africa: Today's GeoGuessr challenge is up! {url}"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":earth_africa: *Today's GeoGuessr challenge*\n<{url}|Play now>  — scores count toward this week's board (resets Monday).",
            },
        }
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


def leaderboard_message(rows: list[dict]) -> tuple[str, list]:
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
    return text, blocks


def challenge_variables(url: str) -> dict:
    return {
        "title": "🌍 Today's GeoGuessr challenge",
        "body": f"Play now: {url}\nScores count toward this week's board (resets Monday).",
    }


def leaderboard_variables(rows: list[dict]) -> dict:
    lines = _leaderboard_lines(rows)
    return {
        "title": "🏆 This week's leaderboard",
        "body": "\n".join(lines) if lines else "No scores yet this week.",
    }


def cookie_expired_variables() -> dict:
    return {
        "title": "⚠️ GeoGuessr cookie expired",
        "body": (
            "The bot can't reach your account. Grab a fresh _ncfa cookie and "
            "update the GEO_NCFA repo secret to get challenges going again."
        ),
    }
