"""Offline checks for the Slack message builders — pure functions, no network,
so they honour the 'never make real Slack calls' rule. Run: python -m tests.test_slack
(from the repo root) or pytest."""
from geobot import slack


def _action_urls(blocks):
    return [e.get("url") for b in blocks if b["type"] == "actions" for e in b["elements"]]


def test_challenge_has_play_button():
    url = "https://www.geoguessr.com/challenge/abc123"
    _, blocks = slack.challenge_message(url)
    assert url in _action_urls(blocks)


def test_leaderboard_buttons_and_count():
    rows = [
        {"name": "A", "total": 100, "rounds": 2},
        {"name": "B", "total": 50, "rounds": 1},
    ]
    _, blocks = slack.leaderboard_message(
        rows, stats_url="https://app/s/league", challenge_url="https://gg/c/xyz"
    )
    ctx = [b for b in blocks if b["type"] == "context"]
    assert ctx and "2 players played this week" in ctx[0]["elements"][0]["text"]
    urls = _action_urls(blocks)
    assert "https://gg/c/xyz" in urls and "https://app/s/league" in urls


def test_leaderboard_singular_count():
    _, blocks = slack.leaderboard_message([{"name": "A", "total": 10, "rounds": 1}])
    ctx = [b for b in blocks if b["type"] == "context"]
    assert "1 player played this week" in ctx[0]["elements"][0]["text"]


def test_leaderboard_no_urls_no_actions():
    _, blocks = slack.leaderboard_message([], None, None)
    assert not any(b["type"] == "actions" for b in blocks)
    assert not any(b["type"] == "context" for b in blocks)  # no count when empty


def test_challenge_variables_button():
    v = slack.challenge_variables("https://gg/c/xyz")
    assert v["button_url"] == "https://gg/c/xyz" and v["button_text"]


def test_leaderboard_variables_button_is_stats():
    rows = [{"name": "A", "total": 10, "rounds": 1}]
    v = slack.leaderboard_variables(rows, stats_url="https://app/s/league")
    assert v["button_url"] == "https://app/s/league" and v["button_text"] == "📊 Stats"
    assert "1 player played this week" in v["players"]
    # no stats url -> the button falls back to the latest challenge, never empty
    v = slack.leaderboard_variables(rows, None, "https://gg/c/xyz")
    assert v["button_url"] == "https://gg/c/xyz" and v["button_text"] == "▶️ Play challenge"


def test_workflow_variables_share_one_shape():
    """All four message types post to ONE workflow trigger, which declares a fixed
    variable set — so every payload needs the same keys and a real button_url, or
    Slack fails the message step with "invalid parameter" (that's what broke the
    reminder: it sent no button_url at all)."""
    rows = [{"name": "A", "total": 10, "rounds": 1}]
    payloads = [
        slack.challenge_variables("https://gg/c/xyz"),
        slack.leaderboard_variables(rows, "https://app/s/l", "https://gg/c/xyz"),
        slack.leaderboard_variables([], None, None),          # no stats, no challenge
        slack.reminder_variables("t", "b", ["A"], "https://gg/c/xyz"),
        slack.reminder_variables("t", "", ["A"], None),       # no link available
        slack.cookie_expired_variables(),
    ]
    assert len({frozenset(p) for p in payloads}) == 1, [sorted(p) for p in payloads]
    assert all(p["button_url"].startswith("https://") for p in payloads)
    assert all(p["button_text"] and p["title"] and p["body"] for p in payloads)


def test_reminder_names_in_message_and_variables():
    names = ["Alice", "Bob"]
    text, blocks = slack.reminder_message("⏰ Still to play", "Get in there!", names)
    body = next(b["text"]["text"] for b in blocks if b["type"] == "section")
    assert "Alice, Bob" in body and "Get in there!" in body
    assert "Alice, Bob" in text
    v = slack.reminder_variables("⏰ Still to play", "Get in there!", names)
    assert v["players"] == "Alice, Bob" and "Alice, Bob" in v["body"]


if __name__ == "__main__":
    test_challenge_has_play_button()
    test_leaderboard_buttons_and_count()
    test_leaderboard_singular_count()
    test_leaderboard_no_urls_no_actions()
    test_challenge_variables_button()
    test_leaderboard_variables_button_is_stats()
    test_workflow_variables_share_one_shape()
    test_reminder_names_in_message_and_variables()
    print("ok")
