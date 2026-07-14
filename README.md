# geo-bot

A self-hosted, multi-tenant app that runs recurring GeoGuessr challenges and
posts them (plus a weekly/season leaderboard) to a chat channel. Sign up, add
your credentials and maps in the UI, define leagues and their games, and the
built-in scheduler handles the rest. Slack is supported today; the transport
layer is pluggable (Discord etc. drop in later).

## Model

- **User** — self-registered account; sees only its own data.
- **Credential** — a GeoGuessr `_ncfa` cookie or a transport token (Slack webhook).
  Encrypted at rest.
- **Map** — a GeoGuessr map saved by paste + validate (id/URL → name + thumbnail).
- **League** — a channel + one GeoGuessr account + the combined weekly/season
  leaderboard + a results schedule + an optional public stats page.
- **Game** — inside a league: one map + challenge settings (time limit, movement
  rules) + a score `weight` + its own "post a new challenge" schedule.

`normal` + `fast` = two games in one league feeding one weighted leaderboard.

## Run it

Local:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export GEO_FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
.venv/bin/python -m geobot.serve          # http://localhost:8080
```

Docker (single container + a `/data` volume for the SQLite db):

```bash
docker build -t geo-bot .
docker run -p 8080:8080 -v geo-bot-data:/data \
  -e GEO_FERNET_KEY=... -e SECRET_KEY=... geo-bot
```

Env vars are documented in `.env.example`. **Keep `GEO_FERNET_KEY` stable** — it
decrypts stored credentials. On Coolify, deploy as a normal web service pointing
at port 8080 with a persistent `/data` volume (no scheduled tasks — the app
schedules itself).

## First-run setup

1. Register an account, then **Credentials** → add a GeoGuessr cookie (the `_ncfa`
   value from a logged-in browser: DevTools → Application → Cookies) and a Slack
   Incoming Webhook URL (api.slack.com/apps → Incoming Webhooks). Slack Workflow
   Builder triggers are supported too — pick "Workflow Builder" as the mode.
2. **Maps** → paste a GeoGuessr map URL/ID and save it.
3. **New league** → pick the channel + GeoGuessr account, set the **leaderboard
   post** schedule + timezone and the **pull interval** (how often scores refresh
   in the background — a separate, silent action from the daily Slack post),
   optionally publish a public stats slug.
4. Add one or more **games** (map + settings + weight + challenge schedule).
5. Use **Run now** on a game / **Post results now** on a league to test without
   waiting for the schedule.

Stats are private by default; a league with a public slug is viewable at
`/s/<slug>`. `weight` scales a game's scores in the combined board so an easier
game doesn't dominate (`1.0` = unweighted).

## Importing existing data

To carry over an old `data/store.json`, create the league and games first
(name the games to match the store's `map` values, e.g. `normal`/`fast`), then:

```bash
.venv/bin/python -m geobot.import_store <league_id> [path/to/store.json]
```

Re-fetch per-round data (guesses, countries, avatars) for a league:

```bash
.venv/bin/python -m geobot.backfill <league_id>
```

## Notes

- Runs as a single process (waitress) so the in-process scheduler fires each job
  once — do not put it behind a multi-worker WSGI server.
- Cookie expiry: each scheduled/Run-now action pings an authenticated endpoint
  first; if the `_ncfa` cookie is dead it posts a ⚠️ alert to the channel instead
  of failing silently. Fix by adding a fresh cookie credential.
- GeoGuessr has no official API; endpoints are reverse-engineered and can change
  without notice — `resolve_map`'s response parsing is best-effort. Fine for a
  private friend group; think twice before scaling.
- Schema changes go in `migrations/NNNN_*.sql` (applied in order on startup).
