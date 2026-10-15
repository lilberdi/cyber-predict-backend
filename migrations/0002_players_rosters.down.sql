DROP TABLE IF EXISTS player_rating_history;
DROP TABLE IF EXISTS player_rating;
DROP TABLE IF EXISTS roster_changes;
DROP TABLE IF EXISTS team_rosters;
ALTER TABLE players
    DROP COLUMN IF EXISTS slug, DROP COLUMN IF EXISTS first_name, DROP COLUMN IF EXISTS last_name,
    DROP COLUMN IF EXISTS nationality, DROP COLUMN IF EXISTS birthday, DROP COLUMN IF EXISTS image_url,
    DROP COLUMN IF EXISTS updated_at;
