CREATE TABLE IF NOT EXISTS teams (
    id            BIGSERIAL PRIMARY KEY,
    external_id   TEXT UNIQUE,
    name          TEXT NOT NULL,
    slug          TEXT,
    image_url     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS teams_name_lower_idx ON teams (lower(name));

CREATE TABLE IF NOT EXISTS players (
    id            BIGSERIAL PRIMARY KEY,
    external_id   TEXT UNIQUE,
    team_id       BIGINT REFERENCES teams (id) ON DELETE SET NULL,
    nickname      TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matches (
    id              BIGSERIAL PRIMARY KEY,
    external_id     TEXT UNIQUE,
    source          TEXT NOT NULL CHECK (source IN ('pandascore', 'dataset', 'fixture')),
    team1_id        BIGINT NOT NULL REFERENCES teams (id),
    team2_id        BIGINT NOT NULL REFERENCES teams (id),
    tournament      TEXT,
    tournament_tier TEXT,
    best_of         INT,
    scheduled_at    TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('upcoming', 'running', 'finished')),
    score1          INT,
    score2          INT,
    winner_team_id  BIGINT REFERENCES teams (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (team1_id <> team2_id)
);

CREATE INDEX IF NOT EXISTS matches_status_scheduled_idx ON matches (status, scheduled_at);
CREATE INDEX IF NOT EXISTS matches_team1_idx ON matches (team1_id);
CREATE INDEX IF NOT EXISTS matches_team2_idx ON matches (team2_id);

CREATE TABLE IF NOT EXISTS match_rosters (
    match_id  BIGINT NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    team_id   BIGINT NOT NULL REFERENCES teams (id),
    player_id BIGINT NOT NULL REFERENCES players (id),
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS team_elo (
    team_id        BIGINT PRIMARY KEY REFERENCES teams (id) ON DELETE CASCADE,
    rating         DOUBLE PRECISION NOT NULL DEFAULT 1500,
    matches_played INT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS predictions (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT NOT NULL UNIQUE REFERENCES matches (id) ON DELETE CASCADE,
    model_name     TEXT NOT NULL,
    model_version  TEXT NOT NULL,
    p_team1_win    DOUBLE PRECISION NOT NULL CHECK (p_team1_win >= 0 AND p_team1_win <= 1),
    p_team2_win    DOUBLE PRECISION NOT NULL CHECK (p_team2_win >= 0 AND p_team2_win <= 1),
    confidence     TEXT,
    top_features   JSONB,
    explanation    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_metrics (
    id                    BIGSERIAL PRIMARY KEY,
    model_name            TEXT NOT NULL,
    model_version         TEXT NOT NULL,
    trained_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_train               INT,
    n_test                INT,
    accuracy              DOUBLE PRECISION,
    log_loss              DOUBLE PRECISION,
    brier                 DOUBLE PRECISION,
    elo_favorite_accuracy DOUBLE PRECISION,
    extra                 JSONB
);
