-- Team Elo after every rated match. Rebuilt from scratch by `python -m ml train`
-- (the same replay that fills team_elo), so it is always consistent with the current rating.
CREATE TABLE IF NOT EXISTS team_elo_history (
    team_id      BIGINT NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
    match_id     BIGINT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    played_at    TIMESTAMPTZ NOT NULL,
    rating_after DOUBLE PRECISION NOT NULL,
    delta        DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (team_id, match_id)
);
CREATE INDEX IF NOT EXISTS team_elo_history_team_at_idx ON team_elo_history (team_id, played_at DESC);

-- Head-to-head and recent form look matches up by team and date.
CREATE INDEX IF NOT EXISTS matches_finished_team1_at_idx ON matches (team1_id, scheduled_at DESC) WHERE status = 'finished';
CREATE INDEX IF NOT EXISTS matches_finished_team2_at_idx ON matches (team2_id, scheduled_at DESC) WHERE status = 'finished';
