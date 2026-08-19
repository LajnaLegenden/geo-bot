-- 0006_season_games.sql — a game belongs to a season, so maps/weights/settings
-- can change from one season to the next.
--
-- History freezes itself: challenges keep pointing at the game row they were
-- created under, so a past season is always scored with the weight and map it
-- was actually played with. Changing next season means editing *its* copies.
--
-- season_id is nullable only because SQLite's ALTER TABLE ADD COLUMN can't take
-- a non-constant default; it is backfilled below and always set by the app.
-- A NULL would be an orphan game: it posts nothing (jobs.post_challenge only
-- fires for the current season's games) and shows on no season's page.

ALTER TABLE games ADD COLUMN season_id INTEGER REFERENCES seasons(id);

-- Existing games become the live season's games.
UPDATE games SET season_id = (
  SELECT s.id FROM seasons s
   WHERE s.league_id = games.league_id AND s.starts_on <= date('now')
   ORDER BY s.starts_on DESC, s.id DESC LIMIT 1
);
-- Safety net for a league whose only season is future-dated (0005 can't produce
-- one, but a hand-edited DB could): fall back to its earliest season.
UPDATE games SET season_id = (
  SELECT s.id FROM seasons s WHERE s.league_id = games.league_id
   ORDER BY s.starts_on, s.id LIMIT 1
) WHERE season_id IS NULL;

CREATE INDEX ix_games_season ON games(season_id);
