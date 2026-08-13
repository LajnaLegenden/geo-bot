"""Transport-agnostic messaging. A transport turns bot events into messages on some
channel; `dest` is whatever that transport needs. For Slack that's either
{mode:"bot", bot_token, signing_secret, channel_id, delivery, league_id} or
{mode:"incoming", url, league_id} — built by jobs._transport.

Transports never read the database: anything requiring a query (like the Slack-user
links behind @-mentions) is resolved by jobs.py and handed in on the rows/entries.

Adding Discord later = implement these methods against a Discord webhook and call
register(DiscordTransport()). Nothing else changes.
"""
from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    kind: str

    def send_challenge(self, dest: dict, url: str, league: str) -> None: ...
    def send_leaderboard(
        self, dest: dict, rows: list[dict], league: str, links: dict | None = None
    ) -> None: ...
    def send_reminder(
        self, dest: dict, title: str, body: str, entries: list[dict],
        play_url: str | None = None,
    ) -> None: ...
    def send_alert(self, dest: dict, kind: str) -> None: ...

    # Only for transports that can edit an already-sent message (the 🔄 Refresh
    # button). jobs.refresh_leaderboard reaches it exclusively via a dest it has
    # already confirmed is bot mode, so there's no capability sniffing.
    def update_leaderboard(
        self, dest: dict, rows: list[dict], links: dict, message_ts: str
    ) -> None: ...


REGISTRY: dict[str, Transport] = {}


def register(t: Transport) -> None:
    REGISTRY[t.kind] = t


def get(kind: str) -> Transport:
    return REGISTRY[kind]
