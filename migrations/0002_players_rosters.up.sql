ALTER TABLE players
    ADD COLUMN IF NOT EXISTS slug        TEXT,
    ADD COLUMN IF NOT EXISTS first_name  TEXT,
    ADD COLUMN IF NOT EXISTS last_name   TEXT,
    ADD COLUMN IF NOT EXISTS nationality TEXT,
    ADD COLUMN IF NOT EXISTS birthday    DATE,
    ADD COLUMN IF NOT EXISTS image_url   TEXT,
    ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ NOT NULL DEFAULT now();

-- Roster history. joined_at of the first snapshot is the moment we first saw the player
-- on the team, not the real join date (PandaScore gives only the current roster).
CREATE TABLE IF NOT EXISTS team_rosters (
    id        BIGSERIAL PRIMARY KEY,
    team_id   BIGINT NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    left_at   TIMESTAMPTZ,
    CHECK (left_at IS NULL OR left_at >= joined_at)
);
-- A player is on at most one team at a time.
CREATE UNIQUE INDEX IF NOT EXISTS team_rosters_open_player_idx ON team_rosters (player_id) WHERE left_at IS NULL;
CREATE INDEX IF NOT EXISTS team_rosters_team_idx ON team_rosters (team_id, joined_at);

-- kind: join (new to us), leave (no team now), transfer (team A -> team B).
CREATE TABLE IF NOT EXISTS roster_changes (
    id           BIGSERIAL PRIMARY KEY,
    player_id    BIGINT NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('join', 'leave', 'transfer')),
    from_team_id BIGINT REFERENCES teams (id) ON DELETE SET NULL,
    to_team_id   BIGINT REFERENCES teams (id) ON DELETE SET NULL,
    changed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS roster_changes_at_idx ON roster_changes (changed_at DESC);

-- Team Impact Rating: Elo of a player computed from team results while on the roster.
CREATE TABLE IF NOT EXISTS player_rating (
    player_id      BIGINT PRIMARY KEY REFERENCES players (id) ON DELETE CASCADE,
    rating         DOUBLE PRECISION NOT NULL,
    matches_played INT NOT NULL DEFAULT 0,
    seed_rating    DOUBLE PRECISION NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS player_rating_history (
    player_id    BIGINT NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    match_id     BIGINT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    team_id      BIGINT NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
    rating_after DOUBLE PRECISION NOT NULL,
    delta        DOUBLE PRECISION NOT NULL,
    played_at    TIMESTAMPTZ,
    PRIMARY KEY (player_id, match_id)
);
CREATE INDEX IF NOT EXISTS player_rating_history_match_idx ON player_rating_history (match_id);
