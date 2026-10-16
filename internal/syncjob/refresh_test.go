package syncjob

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/lilberdi/cyber-predict/internal/pandascore"
	"github.com/lilberdi/cyber-predict/internal/store"
)

var t0 = time.Date(2026, 10, 15, 19, 0, 0, 0, time.UTC)

func stale() store.StaleMatch {
	return store.StaleMatch{ID: 7, Team1ID: 10, Team2ID: 20, PSMatchID: 555, Team1PS: 111, Team2PS: 222, Status: "upcoming", ScheduledAt: t0}
}

func TestDecide(t *testing.T) {
	scores := map[int64]int{111: 2, 222: 1}
	cases := []struct {
		name    string
		st      pandascore.MatchState
		status  string
		outcome Outcome
		check   func(t *testing.T, u store.MatchUpdate)
	}{
		{"team2 won", pandascore.MatchState{Status: "finished", WinnerID: 222, Scores: scores}, "finished", OutcomeFinished, func(t *testing.T, u store.MatchUpdate) {
			if *u.WinnerTeamID != 20 || *u.Score1 != 2 || *u.Score2 != 1 || u.VoidedReason != nil {
				t.Fatalf("bad update: %+v", u)
			}
		}},
		{"forfeit", pandascore.MatchState{Status: "finished", WinnerID: 111, Forfeit: true, Scores: map[int64]int{111: 0, 222: 0}}, "finished", OutcomeVoided, func(t *testing.T, u store.MatchUpdate) {
			if *u.VoidedReason != "forfeit" || u.WinnerTeamID != nil || u.Score1 != nil {
				t.Fatalf("forfeit must not count: %+v", u)
			}
		}},
		{"draw", pandascore.MatchState{Status: "finished", Draw: true, Scores: scores}, "finished", OutcomeVoided, func(t *testing.T, u store.MatchUpdate) {
			if *u.VoidedReason != "draw" {
				t.Fatalf("reason = %v", *u.VoidedReason)
			}
		}},
		{"canceled", pandascore.MatchState{Status: "canceled"}, "finished", OutcomeVoided, func(t *testing.T, u store.MatchUpdate) {
			if *u.VoidedReason != "canceled" {
				t.Fatalf("reason = %v", *u.VoidedReason)
			}
		}},
		{"finished without winner yet", pandascore.MatchState{Status: "finished", Scores: scores}, "upcoming", OutcomePending, nil},
		{"winner is a stranger", pandascore.MatchState{Status: "finished", WinnerID: 999, Scores: scores}, "upcoming", OutcomePending, nil},
		{"finished without scores", pandascore.MatchState{Status: "finished", WinnerID: 111}, "upcoming", OutcomePending, nil},
		{"started", pandascore.MatchState{Status: "running"}, "running", OutcomeRunning, nil},
		{"postponed by two days", pandascore.MatchState{Status: "postponed", ScheduledAt: t0.Add(48 * time.Hour)}, "upcoming", OutcomeRescheduled, func(t *testing.T, u store.MatchUpdate) {
			if u.ScheduledAt == nil || !u.ScheduledAt.Equal(t0.Add(48*time.Hour)) {
				t.Fatalf("scheduled_at = %v", u.ScheduledAt)
			}
		}},
		{"not started, same time", pandascore.MatchState{Status: "not_started", ScheduledAt: t0.Add(20 * time.Second)}, "upcoming", OutcomePending, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			u, out := Decide(stale(), tc.st)
			if out != tc.outcome || u.Status != tc.status {
				t.Fatalf("outcome=%s status=%s, want %s/%s", out, u.Status, tc.outcome, tc.status)
			}
			if tc.check != nil {
				tc.check(t, u)
			}
		})
	}
}

func TestDecideRunningStaysPendingWhenAlreadyRunning(t *testing.T) {
	m := stale()
	m.Status = "running"
	if _, out := Decide(m, pandascore.MatchState{Status: "running"}); out != OutcomePending {
		t.Fatalf("outcome = %s", out)
	}
}

type fakeStore struct {
	stale   []store.StaleMatch
	applied []store.MatchUpdate
	calls   int
}

func (f *fakeStore) StaleMatches(context.Context, time.Duration, int) ([]store.StaleMatch, error) {
	f.calls++
	return f.stale, nil
}

func (f *fakeStore) ApplyMatchUpdate(_ context.Context, u store.MatchUpdate) error {
	f.applied = append(f.applied, u)
	return nil
}

func psServer(t *testing.T, body string, hits *int) *pandascore.Client {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*hits++
		if !strings.Contains(r.URL.Query().Get("filter[id]"), "555") {
			t.Errorf("filter[id] = %q", r.URL.Query().Get("filter[id]"))
		}
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	return pandascore.New(srv.URL, "token")
}

const finishedBody = `[{"id":555,"status":"finished","winner_id":111,"forfeit":false,"draw":false,
 "results":[{"team_id":111,"score":2},{"team_id":222,"score":0}],
 "opponents":[{"type":"Team","opponent":{"id":111,"name":"A"}},{"type":"Team","opponent":{"id":222,"name":"B"}}]}]`

func TestRefreshAppliesResultAndHonoursCooldown(t *testing.T) {
	hits := 0
	fs := &fakeStore{stale: []store.StaleMatch{stale()}}
	now := t0
	r := &Refresher{Store: fs, Client: psServer(t, finishedBody, &hits), Now: func() time.Time { return now }}

	res, err := r.Refresh(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if res.Finished != 1 || len(res.ChangedIDs) != 1 || len(fs.applied) != 1 || *fs.applied[0].WinnerTeamID != 10 {
		t.Fatalf("unexpected result: %+v applied=%+v", res, fs.applied)
	}

	now = now.Add(20 * time.Second)
	_, err = r.Refresh(context.Background())
	var cd ErrCooldown
	if !errors.As(err, &cd) || cd.RetryAfter != 40*time.Second {
		t.Fatalf("want cooldown of 40s, got %v", err)
	}
	if hits != 1 {
		t.Fatalf("PandaScore hit %d times during cooldown, want 1", hits)
	}

	now = now.Add(41 * time.Second)
	if _, err = r.Refresh(context.Background()); err != nil {
		t.Fatalf("after cooldown: %v", err)
	}
	if hits != 2 {
		t.Fatalf("hits = %d, want 2", hits)
	}
}

func TestRefreshWithNothingStaleDoesNotUseQuota(t *testing.T) {
	hits := 0
	fs := &fakeStore{}
	r := &Refresher{Store: fs, Client: psServer(t, "[]", &hits), Now: func() time.Time { return t0 }}
	for i := 0; i < 3; i++ {
		res, err := r.Refresh(context.Background())
		if err != nil || res.Checked != 0 {
			t.Fatalf("res=%+v err=%v", res, err)
		}
	}
	if hits != 0 {
		t.Fatalf("PandaScore hit %d times with nothing to check", hits)
	}
}

func TestRefreshCountsMissingMatchesAsPending(t *testing.T) {
	hits := 0
	fs := &fakeStore{stale: []store.StaleMatch{stale()}}
	r := &Refresher{Store: fs, Client: psServer(t, "[]", &hits), Now: func() time.Time { return t0 }}
	res, err := r.Refresh(context.Background())
	if err != nil || res.Missing != 1 || res.StillPending != 1 || len(fs.applied) != 0 {
		t.Fatalf("res=%+v err=%v", res, err)
	}
}

func TestRefreshWithoutToken(t *testing.T) {
	r := &Refresher{Store: &fakeStore{}, Client: pandascore.New("http://unused", "")}
	if _, err := r.Refresh(context.Background()); !errors.Is(err, ErrNoToken) {
		t.Fatalf("err = %v", err)
	}
}

func TestMatchStatesBatchesOf100(t *testing.T) {
	var requests []int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, len(strings.Split(r.URL.Query().Get("filter[id]"), ",")))
		_, _ = w.Write([]byte("[]"))
	}))
	defer srv.Close()
	ids := make([]int64, 230)
	for i := range ids {
		ids[i] = int64(i + 1)
	}
	if _, err := pandascore.New(srv.URL, "t").MatchStates(context.Background(), ids); err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(requests) != "[100 100 30]" {
		t.Fatalf("batch sizes = %v", requests)
	}
}
