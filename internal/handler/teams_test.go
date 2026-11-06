package handler

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// New routes must not clash with /matches/:id and must validate input before touching the store.
func TestUpsetsRejectsBadThreshold(t *testing.T) {
	r := NewRouter(&API{}, "*")
	for _, q := range []string{"abc", "0.3", "1", "1.5"} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v1/matches/upsets?min_prob="+q, nil))
		if w.Code != http.StatusBadRequest {
			t.Fatalf("min_prob=%s: status = %d, want 400", q, w.Code)
		}
	}
}

func TestHeadToHeadRejectsBadID(t *testing.T) {
	r := NewRouter(&API{}, "*")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/v1/matches/abc/h2h", nil))
	if w.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", w.Code)
	}
}
