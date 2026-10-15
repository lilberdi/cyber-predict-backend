package handler

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

func (a *API) ListUpcoming(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := a.Store.ListUpcoming(c.Request.Context(), limit)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": items})
}

func (a *API) ListFinished(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := a.Store.ListFinishedWithPrediction(c.Request.Context(), limit)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": items})
}

func (a *API) GetMatch(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	item, err := a.Store.GetMatch(c.Request.Context(), id)
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
