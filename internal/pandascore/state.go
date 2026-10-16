package pandascore

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// MaxIDsPerRequest is PandaScore's per_page ceiling: one request covers this many matches.
const MaxIDsPerRequest = 100

type rawResult struct {
	TeamID int64 `json:"team_id"`
	Score  int   `json:"score"`
}

type rawState struct {
	ID          int64          `json:"id"`
	Status      string         `json:"status"`
	BeginAt     string         `json:"begin_at"`
	ScheduledAt string         `json:"scheduled_at"`
	WinnerID    int64          `json:"winner_id"`
	Forfeit     bool           `json:"forfeit"`
	Draw        bool           `json:"draw"`
	Results     []rawResult    `json:"results"`
	Opponents   []opponentWrap `json:"opponents"`
}

// MatchState is the current state of one match as PandaScore reports it.
type MatchState struct {
	ExternalID  string
	Status      string // not_started | running | finished | canceled | postponed
	ScheduledAt time.Time
	WinnerID    int64 // PandaScore team id, 0 when unknown
	Forfeit     bool
	Draw        bool
	Scores      map[int64]int // PandaScore team id -> maps won
	TeamIDs     []int64
}

// MatchStates fetches the current state of matches by PandaScore id (one request per 100 ids).
func (c *Client) MatchStates(ctx context.Context, ids []int64) ([]MatchState, error) {
	if c.Token == "" {
		return nil, fmt.Errorf("PANDASCORE_TOKEN is empty")
	}
	var out []MatchState
	for start := 0; start < len(ids); start += MaxIDsPerRequest {
		end := min(start+MaxIDsPerRequest, len(ids))
		parts := make([]string, 0, end-start)
		for _, id := range ids[start:end] {
			parts = append(parts, strconv.FormatInt(id, 10))
		}
		raw, err := c.get(ctx, "/csgo/matches", url.Values{
			"filter[id]": {strings.Join(parts, ",")},
			"per_page":   {strconv.Itoa(MaxIDsPerRequest)},
		})
		if err != nil {
			return nil, err
		}
		var rows []rawState
		if err := json.Unmarshal(raw, &rows); err != nil {
			return nil, fmt.Errorf("decode match states: %w", err)
		}
		for _, r := range rows {
			out = append(out, normalizeState(r))
		}
	}
	return out, nil
}

func normalizeState(r rawState) MatchState {
	st := MatchState{
		ExternalID: fmt.Sprintf("ps-%d", r.ID),
		Status:     r.Status,
		WinnerID:   r.WinnerID,
		Forfeit:    r.Forfeit,
		Draw:       r.Draw,
		Scores:     map[int64]int{},
	}
	when := r.ScheduledAt
	if when == "" {
		when = r.BeginAt
	}
	if ts, err := time.Parse(time.RFC3339, when); err == nil {
		st.ScheduledAt = ts
	}
	for _, res := range r.Results {
		st.Scores[res.TeamID] = res.Score
	}
	for _, o := range r.Opponents {
		if o.Opponent.ID != 0 {
			st.TeamIDs = append(st.TeamIDs, o.Opponent.ID)
		}
	}
	return st
}
