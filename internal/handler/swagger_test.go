package handler

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSwaggerRoutes(t *testing.T) {
	r := NewRouter(&API{}, "*")

	t.Run("openapi yaml", func(t *testing.T) {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/openapi.yaml", nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("status = %d", w.Code)
		}
		body := w.Body.String()
		if !strings.Contains(body, "Cyber Predict API") {
			t.Fatal("spec title missing")
		}
		if !strings.Contains(body, "Служебные") || !strings.Contains(body, "Матчи") {
			t.Fatal("expected tagged groups in spec")
		}
	})

	t.Run("swagger redirect", func(t *testing.T) {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/swagger", nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusFound {
			t.Fatalf("status = %d, want 302", w.Code)
		}
	})

	t.Run("swagger ui", func(t *testing.T) {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/swagger/", nil)
		r.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("status = %d body=%s", w.Code, w.Body.String())
		}
		if !strings.Contains(w.Body.String(), "swagger-ui") {
			t.Fatal("swagger ui html missing")
		}
	})
}
