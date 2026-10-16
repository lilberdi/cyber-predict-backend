package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/lilberdi/cyber-predict/internal/pandascore"
	"github.com/lilberdi/cyber-predict/internal/store"
	"github.com/lilberdi/cyber-predict/internal/syncjob"
)

type stubStore struct{ stale []store.StaleMatch }

func (s stubStore) StaleMatches(context.Context, time.Duration, int) ([]store.StaleMatch, error) {
	return s.stale, nil
}
func (stubStore) ApplyMatchUpdate(context.Context, store.MatchUpdate) error { return nil }

func post(r http.Handler) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/v1/matches/refresh", nil))
	return w
}

func TestRefreshEndpointCooldownAndErrors(t *testing.T) {
	ps := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("[]")) }))
	defer ps.Close()

	one := []store.StaleMatch{{ID: 1, PSMatchID: 5, ScheduledAt: time.Now().Add(-2 * time.Hour)}}
	ref := &syncjob.Refresher{Store: stubStore{stale: one}, Client: pandascore.New(ps.URL, "token")}
	r := NewRouter(&API{Refresher: ref}, "*")

	w := post(r)
	if w.Code != http.StatusOK {
		t.Fatalf("first call: %d %s", w.Code, w.Body.String())
	}
	var ok struct {
		Data struct {
			Checked       int               `json:"checked"`
			NewlyFinished []json.RawMessage `json:"newly_finished"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &ok); err != nil || ok.Data.Checked != 1 || ok.Data.NewlyFinished == nil {
		t.Fatalf("body = %s", w.Body.String())
	}

	w = post(r)
	if w.Code != http.StatusTooManyRequests || w.Header().Get("Retry-After") == "" {
		t.Fatalf("second call: %d retry-after=%q", w.Code, w.Header().Get("Retry-After"))
	}
	var limited struct {
		Error struct {
			Code  string `json:"code"`
			Retry int    `json:"retry_after_seconds"`
		} `json:"error"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &limited)
	if limited.Error.Code != "cooldown" || limited.Error.Retry < 1 || limited.Error.Retry > 60 {
		t.Fatalf("error body = %s", w.Body.String())
	}

	noToken := NewRouter(&API{Refresher: &syncjob.Refresher{Store: stubStore{}, Client: pandascore.New(ps.URL, "")}}, "*")
	if w = post(noToken); w.Code != http.StatusServiceUnavailable {
		t.Fatalf("no token: %d", w.Code)
	}
	if w = post(NewRouter(&API{}, "*")); w.Code != http.StatusServiceUnavailable {
		t.Fatalf("not configured: %d", w.Code)
	}
}
