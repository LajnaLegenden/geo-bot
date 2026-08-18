-- 0005_seasons.sql — bounded seasons per league.
--
-- NOTE the number: 0004_slack_bot.sql was applied on deployed DBs and then
-- reverted out of the tree (HEAD dfdd95d). migrate.py tracks by filename, so a
-- file named 0004_* here would be recorded-as-done and silently skipped.
--
-- A season is defined only by where it STARTS. It runs from `starts_on`
-- (inclusive) up to the next season's `starts_on` (exclusive), so gaps and
-- overlaps are impossible and there's no end date to keep in sync. The current
-- season is the one with the greatest starts_on <= today, which makes a
-- future-dated season "upcoming" for free — no scheduler job rolls it over.

CREATE TABLE seasons (
  id         INTEGER PRIMARY KEY,
  league_id  INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  starts_on  TEXT NOT NULL,                  -- 'YYYY-MM-DD', inclusive
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (league_id, starts_on)
);
CREATE INDEX ix_seasons_league ON seasons(league_id, starts_on);

-- Every existing league gets a Season 1 covering all of its history, so the
-- invariant "a league always has >= 1 season" holds from the first boot.
INSERT INTO seasons(league_id, name, starts_on)
SELECT id, 'Season 1',
       COALESCE((SELECT MIN(date) FROM challenges WHERE league_id = leagues.id),
                date('now'))
FROM leagues;
