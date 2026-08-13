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

## Slack setup

You create your own Slack app — one per workspace, owned by you, so its name and
icon are yours. There's no OAuth flow and no client secret; you paste two values.

**Set `BASE_URL` first.** It's how Slack reaches the app to deliver button clicks;
without it there's no interactivity at all. The app warns at boot if a bot
credential exists without it.

1. **Credentials** → the *Create your Slack app* card shows a manifest with your
   `BASE_URL` already filled in. Copy it.
2. api.slack.com/apps → **Create New App** → **From a manifest** → pick your
   workspace → paste → create.
3. **Install to Workspace** → Allow.
4. **OAuth & Permissions** → copy the *Bot User OAuth Token* (`xoxb-…`).
5. **Basic Information → App Credentials** → copy the *Signing Secret*.
6. Back in **Credentials** → add a Slack credential, mode **Bot**, pasting the token
   as the secret and the signing secret in its own field. Saving calls `auth.test`,
   so a bad token is rejected right there instead of at tomorrow's first post.
7. In Slack, `/invite @GeoBot` in each channel it should post to. The app has no
   `chat:write.public` scope, so that invite is what grants posting — the channel
   dropdown on a league lists exactly the channels the bot was invited to.

Bot scopes: `chat:write`, `channels:read`, `groups:read`, `im:write`. Only the
interactivity request URL is used — no Events API subscription, no slash commands.

**Incoming webhooks still work** (mode *Incoming webhook*, paste the URL as the
secret) as a fallback if you can't create an app. They're write-only, so that mode
gets link buttons only: no @-mentions, no linking, no Refresh, no DMs.

*Slack Workflow Builder mode was removed* — a trigger declares one fixed variable
set for every post type, which can't express buttons or mentions. Re-point any
league still using one to a bot credential before upgrading.

## First-run setup

1. Register an account, then **Credentials** → add a GeoGuessr cookie (the `_ncfa`
   value from a logged-in browser: DevTools → Application → Cookies) and a Slack
   credential (see **Slack setup** above).
2. **Maps** → paste a GeoGuessr map URL/ID and save it.
3. **New league** → pick the channel + GeoGuessr account, set the **leaderboard
   post** schedule + timezone and the **pull interval** (how often scores refresh
   in the background — a separate, silent action from the daily Slack post),
   optionally publish a public stats slug.
4. Add one or more **games** (map + settings + weight + challenge schedule).
5. Use **Run now** on a game / **Post results now** on a league to test without
   waiting for the schedule.
6. Tell the channel to click **🔗 That's me** on the next post and pick their
   GeoGuessr name (see **Player linking**).

## Player linking and pings

Challenge, leaderboard and reminder posts carry a **🔗 That's me** button. Clicking
it opens a modal listing the league's players who aren't claimed yet; picking one
stores the link. From then on that person is a real Slack `@`-mention in the
leaderboard and the reminder, instead of a plain name.

- Unlinked players stay plain text. `@here` is never used.
- The link is per league, and one Slack user holds one player per league — clicking
  again moves the link rather than adding a second.
- **Reminder delivery** (on the league) is *channel*, *direct message*, or *both*.
  DMs only reach linked players — there's no Slack id for anyone else.
- Anyone in the channel can claim any *unclaimed* player. Only names already visible
  in that channel are selectable, so this is fine for a friend group; it isn't an
  identity check.

The leaderboard post also carries **🔄 Refresh**, which re-pulls scores and edits
the existing message in place rather than posting a new one.

Stats are private by default; a league with a public slug is viewable at
`/s/<slug>`. For the leaderboard's **📊 Stats** button to appear, set the
`BASE_URL` env var (the app's public URL) *and* give the league a public slug —
without both, the button is omitted (no dead link). `weight` scales a game's
scores in the combined board so an easier game doesn't dominate (`1.0` =
unweighted).

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
- `POST /slack/interact` is the only unauthenticated route. It's exempt from the
  session CSRF check (Slack sends no cookie) and authenticated by Slack's `v0=`
  request signature instead, with a ±5 min replay window. Each user's app has its
  own signing secret, so the payload's team id picks the candidates and the HMAC
  decides between them. League ids arrive in button payloads and are re-checked
  against the signing credential before anything happens.
- GeoGuessr has no official API; endpoints are reverse-engineered and can change
  without notice — `resolve_map`'s response parsing is best-effort. Fine for a
  private friend group; think twice before scaling.
- Schema changes go in `migrations/NNNN_*.sql` (applied in order on startup).
