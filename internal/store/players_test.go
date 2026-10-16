package store

import (
	"testing"
	"time"

	"github.com/lilberdi/cyber-predict/internal/model"
)

func TestAssignRanksSharesPlaceOnEqualRating(t *testing.T) {
	r := func(v float64) *float64 { return &v }
	ps := []model.Player{{Rating: r(2005.6)}, {Rating: r(2005.6)}, {Rating: r(2005.2)}, {Rating: r(1990.0)}}
	assignRanks(ps)
	want := []int{1, 1, 3, 4}
	for i, p := range ps {
		if *p.Rank != want[i] {
			t.Fatalf("player %d rank = %d, want %d", i, *p.Rank, want[i])
		}
	}
}

func TestMarkPredictionCorrect(t *testing.T) {
	start := time.Date(2026, 10, 15, 19, 0, 0, 0, time.UTC)
	winner := int64(1)
	reason := "forfeit"
	mk := func(p1 float64, created time.Time) model.Match {
		return model.Match{
			Status: "finished", ScheduledAt: &start, WinnerTeamID: &winner, Team1: model.Team{ID: 1}, Team2: model.Team{ID: 2},
			Prediction: &model.Prediction{PTeam1Win: p1, CreatedAt: created},
		}
	}
	right := mk(0.7, start.Add(-time.Hour))
	MarkPredictionCorrect(&right)
	if right.PredictionCorrect == nil || !*right.PredictionCorrect {
		t.Fatal("favourite won: want correct")
	}
	wrong := mk(0.3, start.Add(-time.Hour))
	MarkPredictionCorrect(&wrong)
	if wrong.PredictionCorrect == nil || *wrong.PredictionCorrect {
		t.Fatal("underdog won: want incorrect")
	}
	late := mk(0.7, start.Add(time.Minute))
	MarkPredictionCorrect(&late)
	if late.PredictionCorrect != nil {
		t.Fatal("prediction made after the start must not be scored")
	}
	voided := mk(0.7, start.Add(-time.Hour))
	voided.VoidedReason = &reason
	MarkPredictionCorrect(&voided)
	if voided.PredictionCorrect != nil {
		t.Fatal("voided match must not be scored")
	}
}
