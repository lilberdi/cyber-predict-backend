package store

import (
	"context"
	"strconv"
	"strings"
	"time"
)

// StaleMatch is a pandascore match that should have started but is still upcoming/running here.
type StaleMatch struct {
	ID          int64
	Team1ID     int64
	Team2ID     int64
	PSMatchID   int64
	Team1PS     int64
	Team2PS     int64
	Status      string
	ScheduledAt time.Time
}

// MatchUpdate is what a refresh writes back. Nil Score/Winner means "unknown".
type MatchUpdate struct {
	ID           int64
	Status       string
	ScheduledAt  *time.Time
	Score1       *int
	Score2       *int
	WinnerTeamID *int64
	VoidedReason *string
}

// StaleMatches lists pandascore matches whose start time passed more than `grace` ago and that
// are still upcoming/running, oldest first.
func (s *Store) StaleMatches(ctx context.Context, grace time.Duration, limit int) ([]StaleMatch, error) {
	rows, err := s.pool.Query(ctx, `
SELECT m.id, m.team1_id, m.team2_id, m.external_id, t1.external_id, t2.external_id, m.status, m.scheduled_at
FROM matches m
JOIN teams t1 ON t1.id = m.team1_id
JOIN teams t2 ON t2.id = m.team2_id
WHERE m.source = 'pandascore' AND m.status IN ('upcoming', 'running')
  AND m.external_id ~ '^ps-[0-9]+$' AND m.scheduled_at IS NOT NULL
  AND m.scheduled_at < now() - make_interval(secs => $1)
ORDER BY m.scheduled_at, m.id
LIMIT $2
`, grace.Seconds(), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]StaleMatch, 0)
	for rows.Next() {
		var (
			sm     StaleMatch
			ext    string
			t1, t2 *string
		)
		if err := rows.Scan(&sm.ID, &sm.Team1ID, &sm.Team2ID, &ext, &t1, &t2, &sm.Status, &sm.ScheduledAt); err != nil {
			return nil, err
		}
		sm.PSMatchID = parsePSID(ext, "ps-")
		if t1 != nil {
			sm.Team1PS = parsePSID(*t1, "ps-team-")
		}
		if t2 != nil {
			sm.Team2PS = parsePSID(*t2, "ps-team-")
		}
		if sm.PSMatchID > 0 {
			out = append(out, sm)
		}
	}
	return out, rows.Err()
}

func parsePSID(ext, prefix string) int64 {
	n, err := strconv.ParseInt(strings.TrimPrefix(ext, prefix), 10, 64)
	if err != nil {
		return 0
	}
	return n
}

func (s *Store) ApplyMatchUpdate(ctx context.Context, u MatchUpdate) error {
	_, err := s.pool.Exec(ctx, `
UPDATE matches
SET status = $2, scheduled_at = COALESCE($3, scheduled_at),
    score1 = $4, score2 = $5, winner_team_id = $6, voided_reason = $7, updated_at = now()
WHERE id = $1
`, u.ID, u.Status, u.ScheduledAt, u.Score1, u.Score2, u.WinnerTeamID, u.VoidedReason)
	return err
}
