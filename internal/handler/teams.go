package handler

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

// RankTeams: GET /api/v1/rankings/teams?limit=50&min_games=10&active_days=90
func (a *API) RankTeams(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	minGames, _ := strconv.Atoi(c.DefaultQuery("min_games", "10"))
	activeDays, _ := strconv.Atoi(c.DefaultQuery("active_days", "90"))
	items, err := a.Store.RankTeams(c.Request.Context(), limit, minGames, activeDays)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": items})
}

// HeadToHead: GET /api/v1/matches/:id/h2h
func (a *API) HeadToHead(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	item, err := a.Store.HeadToHead(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeError(c, http.StatusNotFound, "not_found", "match not found")
		return
	}
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}

// ListUpsets: GET /api/v1/matches/upsets?min_prob=0.75&limit=50
func (a *API) ListUpsets(c *gin.Context) {
	minProb, err := strconv.ParseFloat(c.DefaultQuery("min_prob", "0.75"), 64)
	if err != nil || minProb < 0.5 || minProb >= 1 {
		writeError(c, http.StatusBadRequest, "bad_request", "min_prob must be a number in [0.5, 1)")
		return
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	item, err := a.Store.ListUpsets(c.Request.Context(), minProb, limit)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}
