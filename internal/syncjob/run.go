package syncjob

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/lilberdi/cyber-predict/internal/pandascore"
	"github.com/lilberdi/cyber-predict/internal/store"
)

type Result struct {
	Source          string `json:"source"`
	Fetched         int    `json:"fetched"`
	Kept            int    `json:"kept"`
	Upserted        int    `json:"upserted"`
	Dropped         int    `json:"dropped"`
	FixturesRemoved int64  `json:"fixtures_removed"`
	TopSetSize      int    `json:"top_set_size"`
	Filter          string `json:"filter"`
	Error           string `json:"error,omitempty"`
}

type Job struct {
	Store       *store.Store
	Client      *pandascore.Client
	TopN        int
	RequireBoth bool
}

func (j *Job) Sync(ctx context.Context) Result {
	res := Result{Filter: "at_least_one_top_team"}
	if j.RequireBoth {
		res.Filter = "both_teams_in_top_set"
	}
	if j.TopN <= 0 {
		j.TopN = 60
	}

	eloNames, _ := j.Store.TopTeamNamesByElo(ctx, j.TopN)
	top := TopSet(SeedTop60, eloNames)
	res.TopSetSize = len(top)

	raw, err := j.Client.Upcoming(ctx, 3, 50)
	if err != nil {
		res.Source = "unchanged"
		res.Error = err.Error()
		return res
	}
	res.Source = "pandascore"
	res.Fetched = len(raw)

	kept := make([]pandascore.Match, 0, len(raw))
	for _, m := range raw {
		if KeepMatch(m.Team1.Name, m.Team2.Name, top, j.RequireBoth) {
			kept = append(kept, m)
		}
	}
	// If strict both-in-top emptied the calendar, relax to "at least one".
	if j.RequireBoth && len(kept) == 0 && len(raw) > 0 {
		res.Filter = "both_empty_fallback_at_least_one"
		for _, m := range raw {
			if KeepMatch(m.Team1.Name, m.Team2.Name, top, false) {
				kept = append(kept, m)
			}
		}
	}
	res.Kept = len(kept)
	res.Dropped = res.Fetched - res.Kept

	for _, m := range kept {
		t1, err := j.Store.UpsertTeam(ctx, m.Team1.Name, store.TeamExternalID(m.Team1.ID), m.Team1.Slug, m.Team1.ImageURL)
		if err != nil {
			res.Error = err.Error()
			return res
		}
		t2, err := j.Store.UpsertTeam(ctx, m.Team2.Name, store.TeamExternalID(m.Team2.ID), m.Team2.Slug, m.Team2.ImageURL)
		if err != nil {
			res.Error = err.Error()
			return res
		}
		id, err := j.Store.UpsertUpcoming(ctx, store.UpcomingWrite{
			ExternalID:     m.ExternalID,
			Source:         "pandascore",
			Team1ID:        t1,
			Team2ID:        t2,
			Tournament:     m.Tournament,
			TournamentTier: m.TournamentTier,
			BestOf:         m.BestOf,
			ScheduledAt:    m.ScheduledAt,
			Status:         m.Status,
		})
		if err != nil {
			res.Error = err.Error()
			return res
		}
		if err := j.Store.UpsertEloPrediction(ctx, id, t1, t2, m.Team1.Name, m.Team2.Name); err != nil {
			res.Error = err.Error()
			return res
		}
		res.Upserted++
	}

	removed, err := j.Store.DeleteFixtureUpcoming(ctx)
	if err != nil {
		res.Error = err.Error()
		return res
	}
	res.FixturesRemoved = removed
	return res
}

func (j *Job) Loop(ctx context.Context, every time.Duration) {
	if every <= 0 {
		return
	}
	t := time.NewTicker(every)
	defer t.Stop()
	log.Printf("upcoming sync every %s (top %d)", every, j.TopN)
	run := func() {
		c, cancel := context.WithTimeout(ctx, 90*time.Second)
		defer cancel()
		res := j.Sync(c)
		if res.Error != "" {
			log.Printf("upcoming sync: %s (fetched=%d)", res.Error, res.Fetched)
			return
		}
		log.Printf("upcoming sync: source=%s fetched=%d kept=%d upserted=%d", res.Source, res.Fetched, res.Kept, res.Upserted)
	}
	run()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			run()
		}
	}
}

func ParseInterval(s string) (time.Duration, error) {
	if s == "" {
		return time.Hour, nil
	}
	if s == "0" || s == "off" {
		return 0, nil
	}
	d, err := time.ParseDuration(s)
	if err != nil {
		return 0, fmt.Errorf("SYNC_INTERVAL: %w", err)
	}
	return d, nil
}
