package store

import (
	"testing"

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
