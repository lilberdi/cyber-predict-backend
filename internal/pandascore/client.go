package pandascore

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

const CS2TitleID = "13"

type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

type Team struct {
	ID       int64  `json:"id"`
	Name     string `json:"name"`
	Slug     string `json:"slug"`
	ImageURL string `json:"image_url"`
}

type opponentWrap struct {
	Type     string `json:"type"`
	Opponent Team   `json:"opponent"`
}

type tournament struct {
	Name string `json:"name"`
	Tier string `json:"tier"`
}

type league struct {
	Name string `json:"name"`
}

type rawMatch struct {
	ID            int64          `json:"id"`
	BeginAt       string         `json:"begin_at"`
	ScheduledAt   string         `json:"scheduled_at"`
	Status        string         `json:"status"`
	NumberOfGames int            `json:"number_of_games"`
	Opponents     []opponentWrap `json:"opponents"`
	Tournament    tournament     `json:"tournament"`
	League        league         `json:"league"`
}

type Match struct {
	ExternalID     string
	Team1          Team
	Team2          Team
	ScheduledAt    time.Time
	BestOf         int
	Tournament     string
	TournamentTier string
	Status         string
}

func New(baseURL, token string) *Client {
	if baseURL == "" {
		baseURL = "https://api.pandascore.co"
	}
	return &Client{
		BaseURL: baseURL,
		Token:   token,
		HTTP:    &http.Client{Timeout: 25 * time.Second},
	}
}

func (c *Client) Upcoming(ctx context.Context, pages, perPage int) ([]Match, error) {
	if c.Token == "" {
		return nil, fmt.Errorf("PANDASCORE_TOKEN is empty")
	}
	if pages < 1 {
		pages = 2
	}
	if perPage < 1 || perPage > 100 {
		perPage = 50
	}
	var out []Match
	for page := 1; page <= pages; page++ {
		raw, err := c.get(ctx, "/csgo/matches/upcoming", url.Values{
			"filter[videogame_title]": {CS2TitleID},
			"per_page":                {fmt.Sprintf("%d", perPage)},
			"page":                    {fmt.Sprintf("%d", page)},
			"sort":                    {"begin_at"},
		})
		if err != nil {
			return nil, err
		}
		var rows []rawMatch
		if err := json.Unmarshal(raw, &rows); err != nil {
			return nil, fmt.Errorf("decode upcoming: %w", err)
		}
		if len(rows) == 0 {
			break
		}
		for _, row := range rows {
			if m, ok := normalize(row); ok {
				out = append(out, m)
			}
		}
	}
	return out, nil
}

func (c *Client) get(ctx context.Context, path string, q url.Values) ([]byte, error) {
	u, err := url.Parse(c.BaseURL + path)
	if err != nil {
		return nil, err
	}
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Accept", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("pandascore %d: %s", resp.StatusCode, truncate(string(body), 240))
	}
	return body, nil
}

func normalize(row rawMatch) (Match, bool) {
	var teams []Team
	for _, o := range row.Opponents {
		if o.Opponent.Name == "" {
			continue
		}
		teams = append(teams, o.Opponent)
	}
	if len(teams) < 2 {
		return Match{}, false
	}
	when := row.BeginAt
	if when == "" {
		when = row.ScheduledAt
	}
	ts, err := time.Parse(time.RFC3339, when)
	if err != nil {
		ts = time.Now().UTC()
	}
	status := "upcoming"
	if row.Status == "running" {
		status = "running"
	}
	tour := row.Tournament.Name
	if tour == "" {
		tour = row.League.Name
	}
	bo := row.NumberOfGames
	if bo <= 0 {
		bo = 3
	}
	return Match{
		ExternalID:     fmt.Sprintf("ps-%d", row.ID),
		Team1:          teams[0],
		Team2:          teams[1],
		ScheduledAt:    ts,
		BestOf:         bo,
		Tournament:     tour,
		TournamentTier: row.Tournament.Tier,
		Status:         status,
	}, true
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
