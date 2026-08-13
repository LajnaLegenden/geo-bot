"""Slack message builders (Block Kit) + the legacy incoming-webhook poster.

Every builder returns `(text, blocks)`: `blocks` is the layout, `text` the plain
fallback Slack shows in notifications and push. Nothing here touches the network
except post_to(), and nothing here reads the database — a caller hands in rows that
already carry `slack_user_id` where a player has linked themselves (jobs.py joins
that; see _name_element).

Two delivery modes exist:
  bot      — chat.postMessage with a bot token (slack_api.py). Interactive.
  incoming — a per-channel Incoming Webhook URL, posted by post_to(). No
             interactivity endpoint exists for it, so `league_id` is left None and
             the callback buttons are omitted entirely.
Slack Workflow Builder mode was removed: its trigger declares one fixed variable
set for every post type, which can't express buttons or mentions and failed the
whole message step whenever a payload key was missing.
"""
from __future__ import annotations

import requests


def post_to(url: str, text: str, blocks: list | None = None) -> None:
    """Post to an explicit Incoming Webhook URL (multi-tenant: the URL comes from the
    league's stored credential, not an env var)."""
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    requests.post(url, json=payload, timeout=15).raise_for_status()


# --- pieces ------------------------------------------------------------------

_PLAY = "▶️ Play challenge"
_MEDALS = ["🥇", "🥈", "🥉"]


def _play_button(url: str) -> dict:
    # A button with a `url` and no action_id is a link-button: it just opens the URL,
    # so it needs no interactivity endpoint and works in every mode.
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": _PLAY, "emoji": True},
        "url": url,
        "style": "primary",
    }


def _action_button(text: str, action_id: str, league_id: int) -> dict:
    # A button with an action_id calls back to /slack/interact, so it only belongs on
    # a bot-posted message. `value` carries the league; the endpoint re-checks that
    # the league really belongs to the credential that signed the request.
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "action_id": action_id,
        "value": str(league_id),
    }


def _link_button(league_id: int) -> dict:
    return _action_button("🔗 That's me", "link_player", league_id)


def _actions(*elements) -> list:
    """An actions block, or nothing at all — Slack rejects an empty elements array."""
    els = [e for e in elements if e]
    return [{"type": "actions", "elements": els}] if els else []


def _name_element(entry: dict) -> dict:
    """One player inside a rich_text_section.

    A linked player renders as a real Slack mention — which also *notifies* them,
    the whole point of the linking feature. An unlinked player renders as bold text:
    plain, unremarkable, and deliberately never `@here`.
    """
    uid = entry.get("slack_user_id")
    if uid:
        return {"type": "user", "user_id": uid}
    return {"type": "text", "text": entry["name"], "style": {"bold": True}}


def _ordered_list(sections: list[dict]) -> list:
    """Wrap rich_text_sections in a native numbered list. Empty in, empty out —
    a rich_text_list with no elements is an invalid block."""
    if not sections:
        return []
    return [{"type": "rich_text", "elements": [
        {"type": "rich_text_list", "style": "ordered", "indent": 0, "elements": sections},
    ]}]


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


# --- leaderboard -------------------------------------------------------------

def _leaderboard_lines(rows: list[dict]) -> list[str]:
    """Plain-text ranking for the notification fallback. Mentions don't render in
    `text`, so this always uses display names."""
    lines = []
    for i, r in enumerate(rows[:10]):
        rank = _MEDALS[i] if i < len(_MEDALS) else f"{i + 1}."
        lines.append(f"{rank} {r['name']} — {r['total']:,} pts ({r['rounds']} games)")
    return lines


def _leaderboard_sections(rows: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(rows[:10]):
        els = []
        if i < len(_MEDALS):
            els.append({"type": "text", "text": _MEDALS[i] + " "})
        els.append(_name_element(r))
        els.append({"type": "text", "text": f" — {r['total']:,} pts ({r['rounds']} games)"})
        out.append({"type": "rich_text_section", "elements": els})
    return out


def _players_played(n: int) -> str:
    return f"{n} player{'' if n == 1 else 's'} played this week"


def leaderboard_message(
    rows: list[dict],
    stats_url: str | None = None,
    challenge_url: str | None = None,
    league_id: int | None = None,
) -> tuple[str, list]:
    """This week's board. `rows` are store.weekly_leaderboard's, optionally carrying
    `slack_user_id`. `league_id` set => bot mode => callback buttons included."""
    lines = _leaderboard_lines(rows)
    text = "This week's leaderboard" + (("\n" + "\n".join(lines)) if lines else "")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🏆 This week's leaderboard"}},
    ]
    if rows:
        blocks += _ordered_list(_leaderboard_sections(rows))
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": _players_played(len(rows))},
        ]})
    else:
        blocks.append(_section("_No scores yet this week._"))
    blocks += _actions(
        _play_button(challenge_url) if challenge_url else None,
        {"type": "button", "text": {"type": "plain_text", "text": "📊 Stats", "emoji": True},
         "url": stats_url} if stats_url else None,
        _action_button("🔄 Refresh", "refresh_leaderboard", league_id) if league_id else None,
        _link_button(league_id) if league_id else None,
    )
    return text, blocks


# --- challenge ---------------------------------------------------------------

def challenge_message(url: str, league_id: int | None = None) -> tuple[str, list]:
    text = f":earth_africa: Today's GeoGuessr challenge is up! {url}"
    blocks = [
        _section(":earth_africa: *Today's GeoGuessr challenge*\n"
                 "Scores count toward this week's board (resets Monday)."),
    ]
    blocks += _actions(_play_button(url), _link_button(league_id) if league_id else None)
    return text, blocks


# --- reminder ----------------------------------------------------------------

def reminder_message(
    title: str,
    body: str,
    entries: list[dict],
    play_url: str | None = None,
    league_id: int | None = None,
) -> tuple[str, list]:
    """Nudge the players who still owe today's challenge(s).

    `entries` is store.players_not_played_today's [{key, name}], with
    `slack_user_id` added by jobs.py for anyone who has linked. `title`/`body` are
    the league's UI-configured text; the roster follows as a native numbered list.
    """
    people = ", ".join(e["name"] for e in entries)
    text = f"{title} — {people}"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title}}]
    if body:
        blocks.append(_section(body))
    blocks += _ordered_list(
        [{"type": "rich_text_section", "elements": [_name_element(e)]} for e in entries]
    )
    blocks += _actions(
        _play_button(play_url) if play_url else None,
        _link_button(league_id) if league_id else None,
    )
    return text, blocks


def dm_reminder_message(title: str, body: str, play_url: str | None = None) -> tuple[str, list]:
    """The same nudge, sent one-to-one. No roster (they're the roster) and no link
    button — a DM only reaches players who are already linked."""
    text = title
    blocks = [_section(f"*{title}*" + (f"\n{body}" if body else ""))]
    blocks += _actions(_play_button(play_url) if play_url else None)
    return text, blocks


# --- alerts ------------------------------------------------------------------

def cookie_expired_message() -> tuple[str, list]:
    text = "⚠️ GeoGuessr cookie expired — add a fresh cookie credential."
    blocks = [_section(
        ":warning: *GeoGuessr cookie expired.*\n"
        "The bot can't reach your account. Grab a fresh `_ncfa` cookie from a "
        "logged-in browser and update the league's GeoGuessr credential to get "
        "challenges going again."
    )]
    return text, blocks


# --- modals ------------------------------------------------------------------

OPT_MAX = 75      # Slack's cap on a static_select option's text and value
_TITLE_MAX = 24    # ...and on a modal title


def link_modal(league_id: int, league_name: str, candidates: list[dict]) -> dict:
    """The "🔗 That's me" modal: pick which GeoGuessr player you are.

    `candidates` is [{key, name}] of players in this league who aren't linked yet.
    `private_metadata` carries the league id through to the submission, where it's
    re-authorized against the signing credential. The submission handler re-derives
    the candidate list and rejects a value that isn't in it, so a stale modal (or a
    key truncated by OPT_MAX) fails loudly instead of writing a wrong link.
    """
    return {
        "type": "modal",
        "callback_id": "link_player_submit",
        "private_metadata": str(league_id),
        "title": {"type": "plain_text", "text": "That's me"[:_TITLE_MAX]},
        "submit": {"type": "plain_text", "text": "Link"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [{
            "type": "input",
            "block_id": "player",
            "label": {"type": "plain_text",
                      "text": f"Which player are you in {league_name}?"[:2000]},
            "element": {
                "type": "static_select",
                "action_id": "choice",
                "placeholder": {"type": "plain_text", "text": "Pick your GeoGuessr name"},
                "options": [
                    {"text": {"type": "plain_text", "text": c["name"][:OPT_MAX]},
                     "value": c["key"]}
                    for c in candidates[:100]  # Slack's option limit
                ],
            },
        }],
    }


def notice_modal(body: str) -> dict:
    """A submit-less modal for the dead ends: nobody left to link, or a link that
    just succeeded. Used as a `response_action: update` so it costs no API call."""
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "GeoBot"},
        "close": {"type": "plain_text", "text": "Done"},
        "blocks": [_section(body)],
    }
