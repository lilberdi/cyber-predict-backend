package store

import (
	"math"
	"testing"
	"time"
)

func TestScoreLive(t *testing.T) {
	d1 := time.Date(2026, 10, 20, 12, 0, 0, 0, time.UTC)
	d2 := d1.Add(24 * time.Hour)
	rows := []liveRow{
		{"elo_xgboost", "high", "s", 0.8, true, &d1},    // correct
		{"elo_xgboost", "low", "d", 0.4, true, &d1},     // wrong
		{"elo_xgboost", "medium", "d", 0.7, false, &d2}, // wrong
		{"elo_xgboost", "high", "s", 0.2, false, &d2},   // correct, favorite = team 2 at 0.8
	}
	got := scoreLive(rows)

	if got.Evaluated != 4 || got.Correct != 2 || got.Accuracy != 0.5 {
		t.Fatalf("totals: %+v", got.AccuracyBucket)
	}
	if b := got.ByTier["s"]; b.Evaluated != 2 || b.Correct != 2 {
		t.Fatalf("tier s: %+v", b)
	}
	if b := got.ByTier["d"]; b.Evaluated != 2 || b.Correct != 0 {
		t.Fatalf("tier d: %+v", b)
	}
	if len(got.Timeline) != 2 || got.Timeline[0].Evaluated != 2 || got.Timeline[1].Evaluated != 4 || got.Timeline[1].Accuracy != 0.5 {
		t.Fatalf("timeline: %+v", got.Timeline)
	}
	wantBrier := (0.04 + 0.36 + 0.49 + 0.04) / 4
	if math.Abs(got.Brier-wantBrier) > 1e-9 {
		t.Fatalf("brier %v want %v", got.Brier, wantBrier)
	}
	wantLL := (-math.Log(0.8) - math.Log(0.4) - math.Log(0.3) - math.Log(0.8)) / 4
	if math.Abs(got.LogLoss-wantLL) > 1e-9 {
		t.Fatalf("logloss %v want %v", got.LogLoss, wantLL)
	}
	if got.Since == nil || !got.Since.Equal(d1) {
		t.Fatalf("since: %v", got.Since)
	}
	// favorite bins: 0.8 (x2) -> "0.8-0.9"; 0.6 -> "0.6-0.7"; 0.7 -> "0.7-0.8"
	if len(got.Reliability) != 3 {
		t.Fatalf("reliability: %+v", got.Reliability)
	}
}

func TestScoreLiveEmpty(t *testing.T) {
	got := scoreLive(nil)
	if got.Evaluated != 0 || len(got.Timeline) != 0 || got.Reliability == nil || got.Timeline == nil {
		t.Fatalf("empty: %+v", got)
	}
}
