"""Slack transport: reuses the existing slack.py message/variable builders and
picks the incoming-webhook vs Workflow-Builder path from dest["mode"] (the
branch that used to live in main.py's _emit_* helpers).
"""
from __future__ import annotations

from .. import slack
from .base import register


class SlackTransport:
    kind = "slack"

    def _send(self, dest, message, variables):
        if dest.get("mode") == "workflow":
            slack.post_workflow_to(dest["url"], variables)
        else:
            slack.post_to(dest["url"], *message)

    def send_challenge(self, dest, url, league):
        self._send(dest, slack.challenge_message(url), slack.challenge_variables(url))

    def send_leaderboard(self, dest, rows, league):
        self._send(dest, slack.leaderboard_message(rows), slack.leaderboard_variables(rows))

    def send_alert(self, dest, kind):
        if kind == "cookie_expired":
            self._send(dest, slack.cookie_expired_message(), slack.cookie_expired_variables())


register(SlackTransport())
