"""Offline checks for the Slack message builders — pure functions, no network, so
they honour the 'never make real Slack calls' rule. Run: python -m tests.test_slack
(from the repo root) or pytest."""
from geobot import slack


def _urls(blocks):
    return [e.get("url") for b in blocks if b["type"] == "actions" for e in b["elements"]]


def _action_ids(blocks):
    return [e["action_id"] for b in blocks if b["type"] == "actions"
            for e in b["elements"] if "action_id" in e]


def _list_items(blocks):
    """The rich_text_list's sections, i.e. one entry per ranked player."""
    for b in blocks:
        if b["type"] == "rich_text":
            for el in b["elements"]:
                if el["type"] == "rich_text_list":
                    return el
    return None


def _flat(section):
    """(rendered text, mentioned user ids) for one rich_text_section."""
    text = "".join(e.get("text", "") for e in section["elements"])
    users = [e["user_id"] for e in section["elements"] if e["type"] == "user"]
    return text, users


ROWS = [
    {"key": "a", "name": "Ana", "total": 41203, "rounds": 12, "slack_user_id": "U0ANA"},
    {"key": "b", "name": "Bertil", "total": 22140, "rounds": 7},
]


def test_challenge_has_play_button():
    url = "https://www.geoguessr.com/challenge/abc123"
    _, blocks = slack.challenge_message(url)
    assert url in _urls(blocks)


def test_leaderboard_uses_native_ordered_list():
    _, blocks = slack.leaderboard_message(ROWS)
    lst = _list_items(blocks)
    assert lst and lst["style"] == "ordered", blocks
    assert len(lst["elements"]) == 2


def test_linked_player_is_a_mention_unlinked_is_text():
    _, blocks = slack.leaderboard_message(ROWS)
    first, second = _list_items(blocks)["elements"]
    text, users = _flat(first)
    assert users == ["U0ANA"], first          # linked -> real @-mention (and notifies)
    assert "Ana" not in text, first           # the name comes from the mention, not text
    assert "41,203 pts (12 games)" in text
    text, users = _flat(second)
    assert users == [] and "Bertil" in text, second   # unlinked -> plain bold text


def test_leaderboard_text_fallback_never_uses_mentions():
    text, _ = slack.leaderboard_message(ROWS)
    assert "Ana" in text and "U0ANA" not in text, text


def test_leaderboard_buttons_and_count():
    _, blocks = slack.leaderboard_message(
        ROWS, stats_url="https://app/s/league", challenge_url="https://gg/c/xyz"
    )
    ctx = [b for b in blocks if b["type"] == "context"]
    assert ctx and "2 players played this week" in ctx[0]["elements"][0]["text"]
    urls = _urls(blocks)
    assert "https://gg/c/xyz" in urls and "https://app/s/league" in urls


def test_leaderboard_singular_count():
    _, blocks = slack.leaderboard_message([{"name": "A", "total": 10, "rounds": 1}])
    ctx = [b for b in blocks if b["type"] == "context"]
    assert "1 player played this week" in ctx[0]["elements"][0]["text"]


def test_empty_leaderboard_has_no_list_and_no_actions():
    # a rich_text_list with zero elements is an invalid block, so it must be omitted
    _, blocks = slack.leaderboard_message([], None, None)
    assert _list_items(blocks) is None
    assert not any(b["type"] == "actions" for b in blocks)
    assert not any(b["type"] == "context" for b in blocks)


def test_callback_buttons_only_exist_with_a_league_id():
    """league_id is how the transport says "bot mode". Without it (incoming webhook)
    there's no interactivity endpoint, and a button that errors on click is worse than
    no button."""
    for _, blocks in (slack.leaderboard_message(ROWS, "https://app/s/l", "https://gg/c/x"),
                      slack.challenge_message("https://gg/c/x"),
                      slack.reminder_message("t", "b", ROWS, "https://gg/c/x")):
        assert _action_ids(blocks) == [], blocks

    _, blocks = slack.leaderboard_message(ROWS, "https://app/s/l", "https://gg/c/x", 7)
    assert _action_ids(blocks) == ["refresh_leaderboard", "link_player"], blocks
    values = {e["action_id"]: e["value"] for b in blocks if b["type"] == "actions"
              for e in b["elements"] if "action_id" in e}
    assert values == {"refresh_leaderboard": "7", "link_player": "7"}

    _, blocks = slack.reminder_message("t", "b", ROWS, "https://gg/c/x", 7)
    assert _action_ids(blocks) == ["link_player"], blocks


def test_reminder_lists_everyone_and_pings_the_linked():
    text, blocks = slack.reminder_message("⏰ Still to play", "Get in there!", ROWS)
    items = _list_items(blocks)["elements"]
    assert [_flat(i)[1] for i in items] == [["U0ANA"], []], items
    assert "Bertil" in _flat(items[1])[0]
    body = next(b["text"]["text"] for b in blocks if b["type"] == "section")
    assert body == "Get in there!"
    assert "Ana, Bertil" in text                      # notification fallback
    assert "@here" not in text and "<!here>" not in text


def test_reminder_without_body_has_no_section():
    _, blocks = slack.reminder_message("⏰ Still to play", "", ROWS)
    assert not any(b["type"] == "section" for b in blocks)


def test_dm_reminder_is_personal_and_has_no_link_button():
    _, blocks = slack.dm_reminder_message("⏰ You still owe today", "go on", "https://gg/c/x")
    assert _action_ids(blocks) == []                  # a DM only reaches linked players
    assert _urls(blocks) == ["https://gg/c/x"]


def test_link_modal_options_carry_untruncated_keys():
    long_name = "N" * 200
    view = slack.link_modal(7, "Daily GeoGuessr", [
        {"key": "abc123", "name": long_name}, {"key": "def456", "name": "Bertil"},
    ])
    assert view["private_metadata"] == "7"
    opts = view["blocks"][0]["element"]["options"]
    # display text is capped to Slack's limit; the value (what gets stored) is not,
    # because a truncated key would write a link that never matches a player
    assert len(opts[0]["text"]["text"]) == slack.OPT_MAX
    assert [o["value"] for o in opts] == ["abc123", "def456"]


def test_link_modal_caps_options_at_slacks_limit():
    view = slack.link_modal(1, "L", [{"key": f"k{i}", "name": f"P{i}"} for i in range(150)])
    assert len(view["blocks"][0]["element"]["options"]) == 100


def test_notice_modal_has_no_submit():
    view = slack.notice_modal("done")
    assert "submit" not in view and view["close"]


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
    print("ok")
