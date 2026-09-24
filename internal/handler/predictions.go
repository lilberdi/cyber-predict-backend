package handler

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

func (a *API) GetPrediction(c *gin.Context) {
	id, ok := parseID(c)
	if !ok {
		return
	}
	item, err := a.Store.GetPrediction(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeError(c, http.StatusNotFound, "not_found", "prediction not found")
		return
	}
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}
