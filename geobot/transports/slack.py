"""Slack transport: builds messages with slack.py, then delivers them either through
a bot token (chat.postMessage) or a legacy Incoming Webhook URL, per dest["mode"].

The mode also decides whether callback buttons exist at all — see _league_id.
"""
from __future__ import annotations

from .. import slack, slack_api
from .base import register


class SlackTransport:
    kind = "slack"

    def _post(self, dest, message) -> None:
        text, blocks = message
        if dest.get("mode") == "bot":
            slack_api.post_message(dest["bot_token"], dest["channel_id"], text, blocks)
        else:
            slack.post_to(dest["url"], text, blocks)

    def _league_id(self, dest):
        """The league id, but only in bot mode — slack.py takes it as "include the
        callback buttons". A webhook-posted button with an action_id renders happily
        and then errors when someone clicks it, which is worse than no button, so
        webhook mode gets None and the link-only buttons."""
        return dest.get("league_id") if dest.get("mode") == "bot" else None

    def send_challenge(self, dest, url, league) -> None:
        self._post(dest, slack.challenge_message(url, self._league_id(dest)))

    def send_leaderboard(self, dest, rows, league, links=None) -> None:
        links = links or {}
        self._post(dest, slack.leaderboard_message(
            rows, links.get("stats_url"), links.get("challenge_url"),
            self._league_id(dest),
        ))

    def update_leaderboard(self, dest, rows, links, message_ts) -> None:
        """Edit a leaderboard post in place — the 🔄 Refresh button. Bot mode only
        (a webhook can't edit), which jobs.refresh_leaderboard checks first."""
        text, blocks = slack.leaderboard_message(
            rows, links.get("stats_url"), links.get("challenge_url"),
            self._league_id(dest),
        )
        slack_api.update_message(
            dest["bot_token"], dest["channel_id"], message_ts, text, blocks
        )

    def send_reminder(self, dest, title, body, entries, play_url=None) -> None:
        delivery = dest.get("delivery") or "channel"
        if delivery in ("channel", "both"):
            self._post(dest, slack.reminder_message(
                title, body, entries, play_url, self._league_id(dest)
            ))
        if delivery in ("dm", "both") and dest.get("mode") == "bot":
            self._dm_each(dest, title, body, entries, play_url)

    def _dm_each(self, dest, title, body, entries, play_url) -> None:
        """DM each straggler who has linked themselves. Unlinked players are
        unreachable by definition — there's no Slack id to send to — so a 'dm'-only
        league silently skips them; that's the trade-off for not @here-ing.
        One failed DM (closed conversation, deactivated account) mustn't sink the
        rest of the reminder."""
        token = dest["bot_token"]
        text, blocks = slack.dm_reminder_message(title, body, play_url)
        for e in entries:
            uid = e.get("slack_user_id")
            if not uid:
                continue
            try:
                slack_api.post_message(token, slack_api.open_dm(token, uid), text, blocks)
            except Exception as ex:
                print(f"dm to {uid} failed: {ex}")

    def send_alert(self, dest, kind) -> None:
        if kind == "cookie_expired":
            self._post(dest, slack.cookie_expired_message())


register(SlackTransport())
