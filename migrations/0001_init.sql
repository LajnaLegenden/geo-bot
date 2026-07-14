-- 0001_init.sql — initial schema for the multi-tenant geo-bot app.
--
-- Two-level model: a League owns a channel + combined leaderboard + results
-- schedule and contains many Games (a saved map + challenge settings + weight +
-- its own new-challenge schedule). Challenges/scores are league-scoped so the
-- combined weighted board spans a league's games.
--
-- Booleans are 0/1 INTEGERs, timestamps ISO-8601 TEXT, JSON lives in TEXT
-- columns (guesses/countries). `secret` columns hold Fernet ciphertext.
-- Foreign keys need PRAGMA foreign_keys=ON per connection (set in db.py).

CREATE TABLE users (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE credentials (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('geoguessr', 'slack', 'discord')),
  label      TEXT NOT NULL,
  secret     TEXT NOT NULL,          -- ENCRYPTED (Fernet): _ncfa cookie or webhook URL/token
  meta       TEXT,                   -- JSON, non-secret, e.g. {"mode":"incoming"}
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_credentials_user ON credentials(user_id);

CREATE TABLE maps (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,          -- resolved map name
  map_id     TEXT NOT NULL,          -- GeoGuessr map id/slug (validated on save)
  thumbnail  TEXT,                   -- CDN url, nullable
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_maps_user ON maps(user_id);

CREATE TABLE leagues (
  id                INTEGER PRIMARY KEY,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  transport_cred_id INTEGER NOT NULL REFERENCES credentials(id),  -- the channel
  geo_cred_id       INTEGER NOT NULL REFERENCES credentials(id),  -- shared by its games
  cron_results      TEXT NOT NULL,   -- APScheduler cron: fetch scores + post leaderboard
  tz                TEXT NOT NULL DEFAULT 'UTC',  -- IANA, DST-safe
  public_slug       TEXT UNIQUE,     -- nullable; public read-only stats page segment
  enabled           INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_leagues_user ON leagues(user_id);

CREATE TABLE games (
  id              INTEGER PRIMARY KEY,
  league_id       INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  map_ref         INTEGER NOT NULL REFERENCES maps(id),
  time_limit      INTEGER NOT NULL DEFAULT 0,    -- seconds/round, 0 = unlimited
  forbid_moving   INTEGER NOT NULL DEFAULT 0,
  forbid_zooming  INTEGER NOT NULL DEFAULT 0,
  forbid_rotating INTEGER NOT NULL DEFAULT 0,
  weight          REAL NOT NULL DEFAULT 1.0,     -- score multiplier in the combined board
  cron_challenge  TEXT NOT NULL,                 -- APScheduler cron: post new challenge
  enabled         INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_games_league ON games(league_id);

CREATE TABLE challenges (
  league_id  INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
  game_id    INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  token      TEXT NOT NULL,
  date       TEXT NOT NULL,                      -- 'YYYY-MM-DD'
  url        TEXT NOT NULL,
  countries  TEXT,                               -- JSON list of round country codes
  PRIMARY KEY (league_id, token)                 -- token unique within a league
);
CREATE INDEX ix_challenges_league_date ON challenges(league_id, date);

CREATE TABLE scores (
  id         INTEGER PRIMARY KEY,
  league_id  INTEGER NOT NULL,
  token      TEXT NOT NULL,
  date       TEXT NOT NULL,
  user_id    TEXT,                               -- GeoGuessr player id, nullable
  name       TEXT NOT NULL,
  score      INTEGER NOT NULL,
  pin        TEXT,                               -- avatar url, nullable
  guesses    TEXT,                               -- JSON list of {pts,dist,t,miss}
  FOREIGN KEY (league_id, token)
    REFERENCES challenges(league_id, token) ON DELETE CASCADE
);
CREATE INDEX ix_scores_league_token ON scores(league_id, token);
CREATE INDEX ix_scores_league_date  ON scores(league_id, date);
