package store

import (
	"context"
	"errors"
	"math"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/lilberdi/cyber-predict/internal/model"
)

const (
	FormSize       = 5   // matches in the W/L strip
	H2HWindowDays  = 365 // same window as the h2h_diff feature
	H2HListSize    = 5
	eloHistorySize = 100
)

// countedMatch: finished, has a winner and is not voided (canceled, forfeit, draw).
const countedMatch = `m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.voided_reason IS NULL`

// RankTeams lists teams by Elo, best first. minGames hides teams whose rating is still unreliable;
// activeDays (if > 0) hides teams without a counted match in that many days.
func (s *Store) RankTeams(ctx context.Context, limit, minGames, activeDays int) ([]model.TeamRanking, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	if minGames < 0 {
		minGames = 0
	}
	rows, err := s.pool.Query(ctx, `
SELECT t.id, t.name, t.slug, t.image_url, e.rating, e.matches_played,
       e.rating - COALESCE(
           (SELECT h.rating_after FROM team_elo_history h
             WHERE h.team_id = t.id AND h.played_at <= now() - interval '7 days'
             ORDER BY h.played_at DESC LIMIT 1),
           (SELECT h.rating_after - h.delta FROM team_elo_history h
             WHERE h.team_id = t.id ORDER BY h.played_at LIMIT 1)
       ) AS change_7d,
       lp.last_played
FROM team_elo e
JOIN teams t ON t.id = e.team_id
LEFT JOIN LATERAL (
    SELECT max(m.scheduled_at) AS last_played FROM matches m
    WHERE `+countedMatch+` AND (m.team1_id = t.id OR m.team2_id = t.id)
) lp ON true
WHERE e.matches_played >= $2
  AND ($3 <= 0 OR lp.last_played >= now() - make_interval(days => $3))
ORDER BY e.rating DESC, t.id
LIMIT $1
`, limit, minGames, activeDays)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]model.TeamRanking, 0)
	ids := make([]int64, 0)
	for rows.Next() {
		var r model.TeamRanking
		if err := rows.Scan(&r.Team.ID, &r.Team.Name, &r.Team.Slug, &r.Team.ImageURL,
			&r.Elo, &r.EloMatches, &r.Change7d, &r.LastPlayed); err != nil {
			return nil, err
		}
		if r.Change7d != nil {
			v := math.Round(*r.Change7d*10) / 10
			r.Change7d = &v
		}
		r.Form = []model.FormResult{}
		out = append(out, r)
		ids = append(ids, r.Team.ID)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows.Close()
	assignTeamRanks(out)

	forms, err := s.recentForm(ctx, ids, FormSize, nil)
	if err != nil {
		return nil, err
	}
	for i := range out {
		if f, ok := forms[out[i].Team.ID]; ok {
			out[i].Form = f
		}
	}
	return out, nil
}

// assignTeamRanks gives equal places to equal ratings as shown (rounded): 1, 1, 3.
func assignTeamRanks(rows []model.TeamRanking) {
	for i := range rows {
		rows[i].Rank = i + 1
		if i > 0 && math.Round(rows[i].Elo) == math.Round(rows[i-1].Elo) {
			rows[i].Rank = rows[i-1].Rank
		}
	}
}

// recentForm returns the last n counted matches of each team, newest first, strictly before
// `before` when it is set.
func (s *Store) recentForm(ctx context.Context, teamIDs []int64, n int, before *time.Time) (map[int64][]model.FormResult, error) {
	out := map[int64][]model.FormResult{}
	if len(teamIDs) == 0 {
		return out, nil
	}
	rows, err := s.pool.Query(ctx, `
SELECT x.team_id, f.id, f.scheduled_at, f.won, f.score_for, f.score_against,
       o.id, o.name, o.slug, o.image_url
FROM unnest($1::bigint[]) AS x(team_id)
CROSS JOIN LATERAL (
    SELECT m.id, m.scheduled_at, m.winner_team_id = x.team_id AS won,
           CASE WHEN m.team1_id = x.team_id THEN m.score1 ELSE m.score2 END AS score_for,
           CASE WHEN m.team1_id = x.team_id THEN m.score2 ELSE m.score1 END AS score_against,
           CASE WHEN m.team1_id = x.team_id THEN m.team2_id ELSE m.team1_id END AS opponent_id
    FROM matches m
    WHERE `+countedMatch+` AND (m.team1_id = x.team_id OR m.team2_id = x.team_id)
      AND ($3::timestamptz IS NULL OR m.scheduled_at < $3)
    ORDER BY m.scheduled_at DESC NULLS LAST, m.id DESC
    LIMIT $2
) f
JOIN teams o ON o.id = f.opponent_id
ORDER BY x.team_id, f.scheduled_at DESC NULLS LAST, f.id DESC
`, teamIDs, n, before)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var teamID int64
		var f model.FormResult
		if err := rows.Scan(&teamID, &f.MatchID, &f.PlayedAt, &f.Won, &f.ScoreFor, &f.ScoreAgainst,
			&f.Opponent.ID, &f.Opponent.Name, &f.Opponent.Slug, &f.Opponent.ImageURL); err != nil {
			return nil, err
		}
		out[teamID] = append(out[teamID], f)
	}
	return out, rows.Err()
}

// teamEloHistory returns the last points of a team's Elo, oldest first.
func (s *Store) teamEloHistory(ctx context.Context, teamID int64, n int) ([]model.EloPoint, error) {
	rows, err := s.pool.Query(ctx, `
SELECT h.match_id, h.played_at, h.rating_after, h.delta,
       o.id, o.name, o.slug, o.image_url,
       m.winner_team_id = $1 AS won
FROM (SELECT * FROM team_elo_history WHERE team_id = $1 ORDER BY played_at DESC LIMIT $2) h
LEFT JOIN matches m ON m.id = h.match_id
LEFT JOIN teams o ON o.id = CASE WHEN m.team1_id = $1 THEN m.team2_id ELSE m.team1_id END
ORDER BY h.played_at, h.match_id
`, teamID, n)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.EloPoint, 0)
	for rows.Next() {
		var (
			p                model.EloPoint
			oid              *int64
			oname, oslug, oi *string
		)
		if err := rows.Scan(&p.MatchID, &p.PlayedAt, &p.RatingAfter, &p.Delta, &oid, &oname, &oslug, &oi, &p.Won); err != nil {
			return nil, err
		}
		if oid != nil && oname != nil {
			p.Opponent = &model.Team{ID: *oid, Name: *oname, Slug: oslug, ImageURL: oi}
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// HeadToHead returns meetings of the two teams of a match (before the match) and their form.
func (s *Store) HeadToHead(ctx context.Context, matchID int64) (model.HeadToHead, error) {
	m, err := s.GetMatch(ctx, matchID)
	if err != nil {
		return model.HeadToHead{}, err
	}
	before := time.Now().UTC()
	if m.ScheduledAt != nil && m.ScheduledAt.Before(before) {
		before = *m.ScheduledAt
	}
	h := model.HeadToHead{
		MatchID: m.ID, Team1: m.Team1, Team2: m.Team2, Before: &before, WindowDays: H2HWindowDays,
		Meetings: []model.Match{}, Form1: []model.FormResult{}, Form2: []model.FormResult{},
	}

	err = s.pool.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE m.winner_team_id = $1), count(*) FILTER (WHERE m.winner_team_id = $2)
FROM matches m
WHERE `+countedMatch+` AND m.id <> $3
  AND ((m.team1_id = $1 AND m.team2_id = $2) OR (m.team1_id = $2 AND m.team2_id = $1))
  AND m.scheduled_at < $4 AND m.scheduled_at >= $4 - make_interval(days => $5)
`, m.Team1.ID, m.Team2.ID, m.ID, before, H2HWindowDays).Scan(&h.Team1Wins, &h.Team2Wins)
	if err != nil {
		return h, err
	}

	rows, err := s.pool.Query(ctx, matchSelect+`
WHERE `+countedMatch+` AND m.id <> $3
  AND ((m.team1_id = $1 AND m.team2_id = $2) OR (m.team1_id = $2 AND m.team2_id = $1))
  AND m.scheduled_at < $4
ORDER BY m.scheduled_at DESC, m.id DESC
LIMIT $5
`, m.Team1.ID, m.Team2.ID, m.ID, before, H2HListSize)
	if err != nil {
		return h, err
	}
	for rows.Next() {
		mm, err := scanMatch(rows)
		if err != nil {
			rows.Close()
			return h, err
		}
		MarkPredictionCorrect(&mm)
		h.Meetings = append(h.Meetings, mm)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return h, err
	}

	forms, err := s.recentForm(ctx, []int64{m.Team1.ID, m.Team2.ID}, FormSize, &before)
	if err != nil {
		return h, err
	}
	if f, ok := forms[m.Team1.ID]; ok {
		h.Form1 = f
	}
	if f, ok := forms[m.Team2.ID]; ok {
		h.Form2 = f
	}
	return h, nil
}

// ListUpsets returns counted matches with a pre-match prediction where the favourite had
// p >= threshold and lost, most confident misses first, plus how many such calls there were.
func (s *Store) ListUpsets(ctx context.Context, threshold float64, limit int) (model.Upsets, error) {
	if threshold < 0.5 || threshold >= 1 || math.IsNaN(threshold) {
		threshold = 0.75
	}
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	u := model.Upsets{
		Threshold: threshold,
		Items:     []model.Match{},
		Note:      "Only predictions stored before the match start are counted; voided matches are excluded.",
	}
	const favLost = `((p.p_team1_win > p.p_team2_win) <> (m.winner_team_id = m.team1_id))`
	const confident = countedMatch + ` AND p.created_at <= m.scheduled_at AND GREATEST(p.p_team1_win, p.p_team2_win) >= $1`

	err := s.pool.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE `+favLost+`)
FROM matches m JOIN predictions p ON p.match_id = m.id
WHERE `+confident, threshold).Scan(&u.Confident, &u.Upsets)
	if err != nil {
		return u, err
	}
	if u.Confident > 0 {
		u.Rate = float64(u.Upsets) / float64(u.Confident)
	}

	rows, err := s.pool.Query(ctx, matchSelect+`
WHERE `+confident+` AND `+favLost+`
ORDER BY GREATEST(p.p_team1_win, p.p_team2_win) DESC, m.scheduled_at DESC
LIMIT $2
`, threshold, limit)
	if err != nil {
		return u, err
	}
	defer rows.Close()
	for rows.Next() {
		mm, err := scanMatch(rows)
		if err != nil {
			return u, err
		}
		MarkPredictionCorrect(&mm)
		u.Items = append(u.Items, mm)
	}
	return u, rows.Err()
}

// attachTeamExtras fills Elo history and form of a team card.
func (s *Store) attachTeamExtras(ctx context.Context, d *model.TeamDetail) error {
	hist, err := s.teamEloHistory(ctx, d.ID, eloHistorySize)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	if hist != nil {
		d.EloHistory = hist
	}
	forms, err := s.recentForm(ctx, []int64{d.ID}, FormSize, nil)
	if err != nil {
		return err
	}
	if f, ok := forms[d.ID]; ok {
		d.Form = f
	}
	return nil
}
