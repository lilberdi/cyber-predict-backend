package store

import (
	"context"
	"errors"
	"math"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/lilberdi/cyber-predict/internal/model"
)

const playerSelect = `
SELECT p.id, p.nickname, p.slug, p.first_name, p.last_name, p.nationality, p.image_url,
       t.id, t.name, t.slug, t.image_url, r.joined_at,
       pr.rating, COALESCE(pr.matches_played, 0), COALESCE(pr.matches_played = 0, true)
FROM players p
LEFT JOIN team_rosters r ON r.player_id = p.id AND r.left_at IS NULL
LEFT JOIN teams t ON t.id = r.team_id
LEFT JOIN player_rating pr ON pr.player_id = p.id
`

func scanPlayer(row rowScanner) (model.Player, error) {
	var (
		p     model.Player
		tid   *int64
		tname *string
		tslug *string
		timg  *string
	)
	err := row.Scan(
		&p.ID, &p.Nickname, &p.Slug, &p.FirstName, &p.LastName, &p.Nationality, &p.ImageURL,
		&tid, &tname, &tslug, &timg, &p.JoinedAt,
		&p.Rating, &p.RatedMatches, &p.RatingIsSeed,
	)
	if err != nil {
		return p, err
	}
	if tid != nil && tname != nil {
		p.Team = &model.Team{ID: *tid, Name: *tname, Slug: tslug, ImageURL: timg}
	}
	return p, nil
}

// RankPlayers lists players by Team Impact Rating, best first. minGames filters out rookies
// whose rating is still the team-Elo seed.
func (s *Store) RankPlayers(ctx context.Context, limit, minGames int) ([]model.Player, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := s.pool.Query(ctx, playerSelect+`
WHERE pr.rating IS NOT NULL AND r.id IS NOT NULL AND COALESCE(pr.matches_played, 0) >= $2
ORDER BY pr.rating DESC, p.id
LIMIT $1
`, limit, minGames)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Player, 0)
	for rows.Next() {
		p, err := scanPlayer(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	assignRanks(out)
	return out, rows.Err()
}

// assignRanks gives equal places to equal ratings as shown to the user (rounded to a whole
// number): 1, 1, 3. Input must be sorted by rating, best first.
func assignRanks(players []model.Player) {
	for i := range players {
		rank := i + 1
		if i > 0 && players[i].Rating != nil && players[i-1].Rating != nil &&
			math.Round(*players[i].Rating) == math.Round(*players[i-1].Rating) {
			rank = *players[i-1].Rank
		}
		players[i].Rank = &rank
	}
}

func (s *Store) GetPlayer(ctx context.Context, id int64) (model.PlayerDetail, error) {
	d := model.PlayerDetail{History: []model.RatingPoint{}, Teams: []model.RosterStint{}}
	p, err := scanPlayer(s.pool.QueryRow(ctx, playerSelect+`WHERE p.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return d, ErrNotFound
	}
	if err != nil {
		return d, err
	}
	d.Player = p

	rows, err := s.pool.Query(ctx, `
SELECT match_id, played_at, team_id, rating_after, delta
FROM (SELECT * FROM player_rating_history WHERE player_id = $1 ORDER BY played_at DESC LIMIT 50) h
ORDER BY played_at
`, id)
	if err != nil {
		return d, err
	}
	for rows.Next() {
		var pt model.RatingPoint
		var at *time.Time
		if err := rows.Scan(&pt.MatchID, &at, &pt.TeamID, &pt.RatingAfter, &pt.Delta); err != nil {
			rows.Close()
			return d, err
		}
		if at != nil {
			pt.PlayedAt = *at
		}
		d.History = append(d.History, pt)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return d, err
	}

	rows, err = s.pool.Query(ctx, `
SELECT t.id, t.name, t.slug, t.image_url, r.joined_at, r.left_at
FROM team_rosters r JOIN teams t ON t.id = r.team_id
WHERE r.player_id = $1 ORDER BY r.joined_at DESC
`, id)
	if err != nil {
		return d, err
	}
	defer rows.Close()
	for rows.Next() {
		var st model.RosterStint
		if err := rows.Scan(&st.Team.ID, &st.Team.Name, &st.Team.Slug, &st.Team.ImageURL, &st.JoinedAt, &st.LeftAt); err != nil {
			return d, err
		}
		d.Teams = append(d.Teams, st)
	}
	return d, rows.Err()
}

func (s *Store) GetTeam(ctx context.Context, id int64) (model.TeamDetail, error) {
	d := model.TeamDetail{Roster: []model.Player{}}
	err := s.pool.QueryRow(ctx, `
SELECT t.id, t.name, t.slug, t.image_url, e.rating, COALESCE(e.matches_played, 0)
FROM teams t LEFT JOIN team_elo e ON e.team_id = t.id WHERE t.id = $1
`, id).Scan(&d.ID, &d.Name, &d.Slug, &d.ImageURL, &d.Elo, &d.EloMatches)
	if errors.Is(err, pgx.ErrNoRows) {
		return d, ErrNotFound
	}
	if err != nil {
		return d, err
	}
	rows, err := s.pool.Query(ctx, playerSelect+`
WHERE r.team_id = $1 ORDER BY COALESCE(pr.matches_played, 0) DESC, pr.rating DESC NULLS LAST, p.nickname
`, id)
	if err != nil {
		return d, err
	}
	defer rows.Close()
	for rows.Next() {
		p, err := scanPlayer(rows)
		if err != nil {
			return d, err
		}
		d.Roster = append(d.Roster, p)
	}
	d.RosterNote = "Текущий состав из PandaScore, в списке могут быть запасные. История составов ведётся с момента запуска отслеживания."
	return d, rows.Err()
}

func (s *Store) ListTransfers(ctx context.Context, limit int) ([]model.Transfer, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := s.pool.Query(ctx, `
SELECT c.kind, c.changed_at,
       p.id, p.nickname, p.slug, p.nationality, p.image_url,
       f.id, f.name, f.slug, f.image_url,
       t.id, t.name, t.slug, t.image_url
FROM roster_changes c
JOIN players p ON p.id = c.player_id
LEFT JOIN teams f ON f.id = c.from_team_id
LEFT JOIN teams t ON t.id = c.to_team_id
ORDER BY c.changed_at DESC, c.id DESC
LIMIT $1
`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Transfer, 0)
	for rows.Next() {
		var (
			tr                 model.Transfer
			fid, tid           *int64
			fname, fslug, fimg *string
			tname, tslug, timg *string
		)
		if err := rows.Scan(&tr.Kind, &tr.ChangedAt,
			&tr.Player.ID, &tr.Player.Nickname, &tr.Player.Slug, &tr.Player.Nationality, &tr.Player.ImageURL,
			&fid, &fname, &fslug, &fimg, &tid, &tname, &tslug, &timg); err != nil {
			return nil, err
		}
		if fid != nil && fname != nil {
			tr.FromTeam = &model.Team{ID: *fid, Name: *fname, Slug: fslug, ImageURL: fimg}
		}
		if tid != nil && tname != nil {
			tr.ToTeam = &model.Team{ID: *tid, Name: *tname, Slug: tslug, ImageURL: timg}
		}
		out = append(out, tr)
	}
	return out, rows.Err()
}
