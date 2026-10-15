package handler

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

func (a *API) RankPlayers(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	minGames, _ := strconv.Atoi(c.DefaultQuery("min_games", "0"))
	items, err := a.Store.RankPlayers(c.Request.Context(), limit, minGames)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": items})
}

func (a *API) GetPlayer(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	item, err := a.Store.GetPlayer(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeError(c, http.StatusNotFound, "not_found", "player not found")
		return
	}
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}

func (a *API) GetTeam(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	item, err := a.Store.GetTeam(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeError(c, http.StatusNotFound, "not_found", "team not found")
		return
	}
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}

func (a *API) ListTransfers(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := a.Store.ListTransfers(c.Request.Context(), limit)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": items})
}
