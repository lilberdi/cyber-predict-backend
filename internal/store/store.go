package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/lilberdi/cyber-predict/internal/model"
)

var ErrNotFound = errors.New("not found")

type Store struct {
	pool *pgxpool.Pool
}

func New(ctx context.Context, databaseURL string) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	cfg.MaxConns = 8
	cfg.MinConns = 1
	cfg.MaxConnLifetime = time.Hour

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("connect postgres: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}
	return &Store{pool: pool}, nil
}

func (s *Store) Close() {
	s.pool.Close()
}

func (s *Store) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}

const matchSelect = `
SELECT
    m.id, m.external_id, m.source, m.status, m.best_of, m.scheduled_at,
    m.tournament, m.tournament_tier, m.score1, m.score2, m.winner_team_id,
    t1.id, t1.name, t1.slug, t1.image_url,
    t2.id, t2.name, t2.slug, t2.image_url,
    p.model_name, p.model_version, p.p_team1_win, p.p_team2_win,
    p.confidence, p.top_features, p.explanation, p.created_at
FROM matches m
JOIN teams t1 ON t1.id = m.team1_id
JOIN teams t2 ON t2.id = m.team2_id
LEFT JOIN predictions p ON p.match_id = m.id
`

func (s *Store) ListUpcoming(ctx context.Context, limit int) ([]model.Match, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := s.pool.Query(ctx, matchSelect+`
WHERE m.status IN ('upcoming', 'running')
ORDER BY m.scheduled_at NULLS LAST, m.id
LIMIT $1
`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]model.Match, 0)
	for rows.Next() {
		m, err := scanMatch(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func (s *Store) GetMatch(ctx context.Context, id int64) (model.Match, error) {
	row := s.pool.QueryRow(ctx, matchSelect+`WHERE m.id = $1`, id)
	m, err := scanMatch(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Match{}, ErrNotFound
	}
	return m, err
}

func (s *Store) GetPrediction(ctx context.Context, matchID int64) (model.Prediction, error) {
	row := s.pool.QueryRow(ctx, `
SELECT match_id, model_name, model_version, p_team1_win, p_team2_win,
       confidence, top_features, explanation, created_at
FROM predictions
WHERE match_id = $1
`, matchID)

	var p model.Prediction
	var top []byte
	err := row.Scan(
		&p.MatchID, &p.ModelName, &p.ModelVersion, &p.PTeam1Win, &p.PTeam2Win,
		&p.Confidence, &top, &p.Explanation, &p.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Prediction{}, ErrNotFound
	}
	if err != nil {
		return model.Prediction{}, err
	}
	p.TopFeatures = decodeFeatures(top)
	return p, nil
}

func (s *Store) LatestMetrics(ctx context.Context) (model.ModelMetrics, error) {
	row := s.pool.QueryRow(ctx, `
SELECT model_name, model_version, trained_at, n_train, n_test,
       accuracy, log_loss, brier, elo_favorite_accuracy
FROM model_metrics
ORDER BY trained_at DESC, id DESC
LIMIT 1
`)
	var m model.ModelMetrics
	err := row.Scan(
		&m.ModelName, &m.ModelVersion, &m.TrainedAt, &m.NTrain, &m.NTest,
		&m.Accuracy, &m.LogLoss, &m.Brier, &m.EloFavoriteAccuracy,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.ModelMetrics{}, ErrNotFound
	}
	return m, err
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanMatch(row rowScanner) (model.Match, error) {
	var (
		m          model.Match
		predName   *string
		predVer    *string
		p1         *float64
		p2         *float64
		confidence *string
		top        []byte
		explain    *string
		created    *time.Time
	)
	err := row.Scan(
		&m.ID, &m.ExternalID, &m.Source, &m.Status, &m.BestOf, &m.ScheduledAt,
		&m.Tournament, &m.TournamentTier, &m.Score.Team1, &m.Score.Team2, &m.WinnerTeamID,
		&m.Team1.ID, &m.Team1.Name, &m.Team1.Slug, &m.Team1.ImageURL,
		&m.Team2.ID, &m.Team2.Name, &m.Team2.Slug, &m.Team2.ImageURL,
		&predName, &predVer, &p1, &p2, &confidence, &top, &explain, &created,
	)
	if err != nil {
		return model.Match{}, err
	}
	if predName != nil && p1 != nil && p2 != nil && created != nil {
		m.Prediction = &model.Prediction{
			MatchID:      m.ID,
			ModelName:    *predName,
			ModelVersion: valueOr(predVer, ""),
			PTeam1Win:    *p1,
			PTeam2Win:    *p2,
			Confidence:   confidence,
			TopFeatures:  decodeFeatures(top),
			Explanation:  explain,
			CreatedAt:    *created,
		}
	}
	return m, nil
}

func valueOr(v *string, fallback string) string {
	if v == nil {
		return fallback
	}
	return *v
}
