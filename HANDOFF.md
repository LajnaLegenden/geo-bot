# Handoff: add Slack Workflow Builder webhook trigger

## Context

This repo is a GeoGuessr Slack bot that runs on GitHub Actions (free cron), with no
database — state lives in `data/store.json`, committed back to the repo each run.

Current behavior:
- `python -m geobot.main new` — creates a daily GeoGuessr challenge, posts the link to Slack.
- `python -m geobot.main update` — refreshes scores for the last 7 days, posts a rolling
  7-day leaderboard to Slack.
- Both first call `GeoGuessr.check_auth()`; if the `_ncfa` cookie is dead, the bot posts a
  ⚠️ warning to Slack and exits.

Slack posting today goes through an **incoming webhook** (`SLACK_WEBHOOK_URL`) and sends full
Block Kit payloads (`geobot/slack.py`).

## Goal

Add support for posting via a **Slack Workflow Builder "From a webhook" trigger** as an
alternative to the incoming webhook. The user has (or will) build a workflow in Slack that
declares two trigger variables — `title` and `body` — and posts them into a channel.

Workflow Builder webhook triggers require:
- `Content-Type: application/json`
- A flat JSON body whose keys exactly match the declared variables (`title`, `body`).
- No Block Kit — the workflow template in Slack handles layout, so we send plain text only.

## Tasks

1. **`geobot/slack.py`** — add a `post_workflow(variables: dict) -> None` that POSTs the dict
   as JSON to `os.environ["SLACK_WORKFLOW_URL"]` (raise_for_status, 15s timeout). Keep the
   existing `post()` untouched.

2. **`geobot/slack.py`** — add plain-text builders that return `{"title", "body"}` dicts
   (no Block Kit) mirroring the existing message helpers:
   - `challenge_variables(url) -> dict`
   - `leaderboard_variables(rows, days=7) -> dict` — build the ranked text (medals fine as
     unicode 🥇🥈🥉, then `4.`, `5.`, …) into the `body` string.
   - `cookie_expired_variables() -> dict`

3. **`geobot/main.py`** — introduce a sink selector. Read `SLACK_SINK` env var:
   - `SLACK_SINK=incoming` (default) → current Block Kit path via `slack.post`.
   - `SLACK_SINK=workflow` → build variables and send via `slack.post_workflow`.
   Refactor so `cmd_new`, `cmd_update`, and the auth-failure alert all route through one
   `_emit_*` helper per message type that picks the sink. Don't duplicate the ranking logic.

4. **`.github/workflows/bot.yml`** — add `SLACK_WORKFLOW_URL: ${{ secrets.SLACK_WORKFLOW_URL }}`
   and `SLACK_SINK: incoming` to the run step's `env:`. Leave `incoming` as the default so
   existing setups keep working.

5. **`README.md`** — add a short "Slack Workflow Builder (alternative)" section: how to create
   the workflow, declare `title`/`body` variables, get the webhook URL, set the
   `SLACK_WORKFLOW_URL` secret, and flip `SLACK_SINK` to `workflow`. Note the tradeoff: no
   Block Kit / weaker formatting, but editable in Slack by non-technical users.

## Constraints & notes

- Keep the incoming-webhook path fully working as the default — this is additive, a fallback,
  not a replacement.
- No new dependencies; `requests` is already used.
- GeoGuessr endpoints are unofficial; JSON field names in `geobot/geoguessr.py` may drift and
  are the most likely thing to need adjusting if API calls fail — out of scope here, just be
  aware when testing `new`/`update` live.
- Storage schema and the rolling-7-day aggregation in `geobot/store.py` are correct and tested;
  don't change them.

## Verification

- `python -c "from geobot import slack; print(slack.leaderboard_variables([{'name':'Ana','total':20000,'rounds':2}]))"`
  should return a dict with `title` and `body` string keys, no Block Kit.
- With `SLACK_SINK=workflow` and a dummy `SLACK_WORKFLOW_URL`, `main.py` should attempt a POST
  to that URL (mock or point at a request-capture endpoint to confirm the flat payload shape).
- With `SLACK_SINK` unset, behavior is byte-for-byte the same as today.

## Env / secrets summary

| var | purpose |
|-----|---------|
| `GEO_NCFA` | GeoGuessr session cookie |
| `SLACK_WEBHOOK_URL` | incoming webhook (default sink) |
| `SLACK_WORKFLOW_URL` | Workflow Builder trigger URL (new) |
| `SLACK_SINK` | `incoming` (default) or `workflow` |
