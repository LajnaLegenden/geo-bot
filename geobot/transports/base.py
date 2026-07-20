"""Transport-agnostic messaging. A transport turns bot events into messages on
some channel; `dest` is whatever that transport needs (for Slack: a decrypted
webhook URL + mode). Register one per `kind`; the rest of the app only ever
touches get(kind).

Adding Discord later = implement these three methods against a Discord webhook
and call register(DiscordTransport()). Nothing else changes.
"""
from __future__ import annotations

from typing import Protocol


class Transport(Protocol):
    kind: str

    def send_challenge(self, dest: dict, url: str, league: str) -> None: ...
    def send_leaderboard(
        self, dest: dict, rows: list[dict], league: str, links: dict | None = None
    ) -> None: ...
    def send_alert(self, dest: dict, kind: str) -> None: ...


REGISTRY: dict[str, Transport] = {}


def register(t: Transport) -> None:
    REGISTRY[t.kind] = t


def get(kind: str) -> Transport:
    return REGISTRY[kind]
