package store

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/lilberdi/cyber-predict/internal/model"
)

func (s *Store) UpsertTeam(ctx context.Context, name, externalID, slug, imageURL string) (int64, error) {
	var id int64
	err := s.pool.QueryRow(ctx, `SELECT id FROM teams WHERE lower(name) = lower($1)`, name).Scan(&id)
	if err == nil {
		_, err = s.pool.Exec(ctx, `
			UPDATE teams
			SET external_id = COALESCE(teams.external_id, NULLIF($2, '')),
			    slug = COALESCE(NULLIF($3, ''), teams.slug),
			    image_url = COALESCE(NULLIF($4, ''), teams.image_url)
			WHERE id = $1
		`, id, externalID, slug, imageURL)
		return id, err
	}
	if externalID != "" {
		err = s.pool.QueryRow(ctx, `
			INSERT INTO teams (external_id, name, slug, image_url)
			VALUES ($1, $2, NULLIF($3, ''), NULLIF($4, ''))
			ON CONFLICT (external_id) DO UPDATE
				SET name = EXCLUDED.name,
				    slug = COALESCE(EXCLUDED.slug, teams.slug),
				    image_url = COALESCE(EXCLUDED.image_url, teams.image_url)
			RETURNING id
		`, externalID, name, slug, imageURL).Scan(&id)
		return id, err
	}
	err = s.pool.QueryRow(ctx, `
		INSERT INTO teams (name, slug, image_url)
		VALUES ($1, NULLIF($2, ''), NULLIF($3, ''))
		RETURNING id
	`, name, slug, imageURL).Scan(&id)
	return id, err
}

type UpcomingWrite struct {
	ExternalID     string
	Source         string
	Team1ID        int64
	Team2ID        int64
	Tournament     string
	TournamentTier string
	BestOf         int
	ScheduledAt    time.Time
	Status         string
}

func (s *Store) UpsertUpcoming(ctx context.Context, in UpcomingWrite) (int64, error) {
	if in.Source == "" {
		in.Source = "pandascore"
	}
	if in.Status == "" {
		in.Status = "upcoming"
	}
	if in.BestOf <= 0 {
		in.BestOf = 3
	}
	var id int64
	err := s.pool.QueryRow(ctx, `
		INSERT INTO matches (
			external_id, source, team1_id, team2_id, tournament, tournament_tier,
			best_of, scheduled_at, status
		)
		VALUES ($1, $2, $3, $4, NULLIF($5, ''), NULLIF($6, ''), $7, $8, $9)
		ON CONFLICT (external_id) DO UPDATE
			SET scheduled_at = EXCLUDED.scheduled_at,
			    status = EXCLUDED.status,
			    tournament = COALESCE(EXCLUDED.tournament, matches.tournament),
			    updated_at = now()
		RETURNING id
	`, in.ExternalID, in.Source, in.Team1ID, in.Team2ID, in.Tournament, in.TournamentTier, in.BestOf, in.ScheduledAt, in.Status).Scan(&id)
	return id, err
}

func (s *Store) DeleteFixtureUpcoming(ctx context.Context) (int64, error) {
	tag, err := s.pool.Exec(ctx, `
		DELETE FROM matches
		WHERE source = 'fixture' AND status IN ('upcoming', 'running')
	`)
	if err != nil {
		return 0, err
	}
	return tag.RowsAffected(), nil
}

func (s *Store) TopTeamNamesByElo(ctx context.Context, n int) ([]string, error) {
	if n <= 0 {
		n = 60
	}
	rows, err := s.pool.Query(ctx, `
		SELECT t.name
		FROM team_elo e
		JOIN teams t ON t.id = e.team_id
		ORDER BY e.rating DESC
		LIMIT $1
	`, n)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		names = append(names, name)
	}
	return names, rows.Err()
}

func (s *Store) EloByTeamID(ctx context.Context, teamID int64) float64 {
	var r float64
	err := s.pool.QueryRow(ctx, `SELECT rating FROM team_elo WHERE team_id = $1`, teamID).Scan(&r)
	if err != nil {
		return 1500
	}
	return r
}

func (s *Store) UpsertEloPrediction(ctx context.Context, matchID, team1ID, team2ID int64, team1Name, team2Name string) error {
	r1 := s.EloByTeamID(ctx, team1ID)
	r2 := s.EloByTeamID(ctx, team2ID)
	p1 := 1.0 / (1.0 + math.Pow(10, (r2-r1)/400.0))
	p2 := 1 - p1
	gap := math.Abs(p1 - 0.5)
	conf := "high"
	if gap < 0.07 {
		conf = "low"
	} else if gap < 0.15 {
		conf = "medium"
	}
	fav := team1Name
	if p1 < 0.5 {
		fav = team2Name
	}
	diff := r1 - r2
	impact := "favors_team1"
	if diff < 0 {
		impact = "favors_team2"
	}
	top := []model.FeatureContribution{{
		Name:   "elo_diff",
		Value:  math.Round(diff*100) / 100,
		Impact: impact,
	}}
	raw, _ := json.Marshal(top)
	explain := fmt.Sprintf("%s оценивается выше (%.0f%% для %s). Разница Elo %+.0f (онлайн-пересчёт после sync).", fav, p1*100, team1Name, diff)
	_, err := s.pool.Exec(ctx, `
		INSERT INTO predictions (
			match_id, model_name, model_version,
			p_team1_win, p_team2_win, confidence, top_features, explanation
		)
		VALUES ($1, 'elo_sync', '0.1.0', $2, $3, $4, $5::jsonb, $6)
		ON CONFLICT (match_id) DO UPDATE
			SET model_name = EXCLUDED.model_name,
			    p_team1_win = EXCLUDED.p_team1_win,
			    p_team2_win = EXCLUDED.p_team2_win,
			    confidence = EXCLUDED.confidence,
			    top_features = EXCLUDED.top_features,
			    explanation = EXCLUDED.explanation,
			    created_at = now()
			WHERE predictions.model_name = 'elo_sync'
	`, matchID, p1, p2, conf, string(raw), explain)
	return err
}

func TeamExternalID(id int64) string {
	if id == 0 {
		return ""
	}
	return fmt.Sprintf("ps-team-%d", id)
}
