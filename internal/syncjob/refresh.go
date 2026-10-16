package syncjob

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/lilberdi/cyber-predict/internal/pandascore"
	"github.com/lilberdi/cyber-predict/internal/store"
)

const (
	// StartGrace: a match is checked only this long after its scheduled start.
	StartGrace = 30 * time.Minute
	// RefreshBatch: matches per refresh; one PandaScore request covers all of them.
	RefreshBatch = pandascore.MaxIDsPerRequest
	// DefaultCooldown protects the PandaScore quota from a button that anyone can press.
	DefaultCooldown = 60 * time.Second
	rescheduleSlack = time.Minute
)

// ErrCooldown means a refresh ran recently; retry after RetryAfter.
type ErrCooldown struct{ RetryAfter time.Duration }

func (e ErrCooldown) Error() string {
	return fmt.Sprintf("refresh is on cooldown, retry in %ds", int(e.RetryAfter.Seconds()+0.999))
}

var ErrNoToken = errors.New("PandaScore token is not configured")

type Outcome string

const (
	OutcomePending     Outcome = "pending"
	OutcomeFinished    Outcome = "finished"
	OutcomeVoided      Outcome = "voided"
	OutcomeRunning     Outcome = "running"
	OutcomeRescheduled Outcome = "rescheduled"
)

type RefreshResult struct {
	Checked      int     `json:"checked"`
	Finished     int     `json:"finished"`
	Voided       int     `json:"voided"`
	Running      int     `json:"running"`
	Rescheduled  int     `json:"rescheduled"`
	StillPending int     `json:"still_pending"`
	Missing      int     `json:"missing"`
	CooldownSecs int     `json:"cooldown_seconds"`
	ChangedIDs   []int64 `json:"-"` // finished or voided matches, for the response body
}

// MatchStore is the part of the store a refresh needs.
type MatchStore interface {
	StaleMatches(ctx context.Context, grace time.Duration, limit int) ([]store.StaleMatch, error)
	ApplyMatchUpdate(ctx context.Context, u store.MatchUpdate) error
}

// Refresher brings stale upcoming/running matches up to date on demand.
type Refresher struct {
	Store    MatchStore
	Client   *pandascore.Client
	Cooldown time.Duration
	Now      func() time.Time

	mu   sync.Mutex
	last time.Time
}

func (r *Refresher) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

func (r *Refresher) cooldown() time.Duration {
	if r.Cooldown > 0 {
		return r.Cooldown
	}
	return DefaultCooldown
}

// Refresh checks stale matches with one PandaScore request and stores the new state.
// Concurrent callers queue on the mutex and then hit the cooldown, so the API is called once.
func (r *Refresher) Refresh(ctx context.Context) (RefreshResult, error) {
	res := RefreshResult{CooldownSecs: int(r.cooldown().Seconds())}
	if r.Client == nil || r.Client.Token == "" {
		return res, ErrNoToken
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	if wait := r.cooldown() - r.now().Sub(r.last); !r.last.IsZero() && wait > 0 {
		return res, ErrCooldown{RetryAfter: wait}
	}
	stale, err := r.Store.StaleMatches(ctx, StartGrace, RefreshBatch)
	if err != nil {
		return res, err
	}
	res.Checked = len(stale)
	if len(stale) == 0 {
		return res, nil
	}

	r.last = r.now() // any real API attempt uses the quota, successful or not
	ids := make([]int64, len(stale))
	byPS := make(map[string]store.StaleMatch, len(stale))
	for i, m := range stale {
		ids[i] = m.PSMatchID
		byPS[fmt.Sprintf("ps-%d", m.PSMatchID)] = m
	}
	states, err := r.Client.MatchStates(ctx, ids)
	if err != nil {
		return res, err
	}
	seen := map[string]bool{}
	for _, st := range states {
		m, ok := byPS[st.ExternalID]
		if !ok {
			continue
		}
		seen[st.ExternalID] = true
		upd, outcome := Decide(m, st)
		switch outcome {
		case OutcomePending:
			res.StillPending++
			continue
		case OutcomeFinished:
			res.Finished++
			res.ChangedIDs = append(res.ChangedIDs, m.ID)
		case OutcomeVoided:
			res.Voided++
			res.ChangedIDs = append(res.ChangedIDs, m.ID)
		case OutcomeRunning:
			res.Running++
		case OutcomeRescheduled:
			res.Rescheduled++
		}
		if err := r.Store.ApplyMatchUpdate(ctx, upd); err != nil {
			return res, err
		}
	}
	for ext := range byPS {
		if !seen[ext] {
			res.Missing++
			res.StillPending++
		}
	}
	return res, nil
}

// Decide maps PandaScore's view of a match to what we store.
func Decide(m store.StaleMatch, st pandascore.MatchState) (store.MatchUpdate, Outcome) {
	upd := store.MatchUpdate{ID: m.ID, Status: m.Status}
	void := func(reason string) (store.MatchUpdate, Outcome) {
		upd.Status = "finished"
		upd.VoidedReason = &reason
		return upd, OutcomeVoided
	}
	switch st.Status {
	case "canceled":
		return void("canceled")
	case "finished":
		if st.Draw {
			return void("draw")
		}
		if st.Forfeit {
			return void("forfeit")
		}
		return finishedUpdate(m, st, upd)
	case "running":
		if m.Status == "running" {
			return upd, OutcomePending
		}
		upd.Status = "running"
		return upd, OutcomeRunning
	default: // not_started, postponed
		if !st.ScheduledAt.IsZero() && st.ScheduledAt.Sub(m.ScheduledAt).Abs() > rescheduleSlack {
			t := st.ScheduledAt
			upd.Status = "upcoming"
			upd.ScheduledAt = &t
			return upd, OutcomeRescheduled
		}
		return upd, OutcomePending
	}
}

func finishedUpdate(m store.StaleMatch, st pandascore.MatchState, upd store.MatchUpdate) (store.MatchUpdate, Outcome) {
	if st.WinnerID == 0 {
		return upd, OutcomePending
	}
	var winner int64
	switch st.WinnerID {
	case m.Team1PS:
		winner = m.Team1ID
	case m.Team2PS:
		winner = m.Team2ID
	default:
		return upd, OutcomePending // result not published yet, or teams do not match
	}
	s1, ok1 := st.Scores[m.Team1PS]
	s2, ok2 := st.Scores[m.Team2PS]
	if !ok1 || !ok2 {
		return upd, OutcomePending
	}
	upd.Status = "finished"
	upd.Score1, upd.Score2, upd.WinnerTeamID = &s1, &s2, &winner
	return upd, OutcomeFinished
}
