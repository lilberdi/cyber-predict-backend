package store

import (
	"testing"

	"github.com/lilberdi/cyber-predict/internal/model"
)

func TestAssignTeamRanksSharesPlaceOnEqualRating(t *testing.T) {
	rows := []model.TeamRanking{{Elo: 2010.4}, {Elo: 2009.6}, {Elo: 1990}, {Elo: 1989.6}, {Elo: 1900}}
	assignTeamRanks(rows)
	want := []int{1, 1, 3, 3, 5}
	for i, r := range rows {
		if r.Rank != want[i] {
			t.Fatalf("row %d rank = %d, want %d", i, r.Rank, want[i])
		}
	}
}
