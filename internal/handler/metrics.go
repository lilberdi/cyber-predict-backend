package handler

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

func (a *API) GetLiveAccuracy(c *gin.Context) {
	item, err := a.Store.LiveAccuracy(c.Request.Context())
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}

func (a *API) GetMetrics(c *gin.Context) {
	item, err := a.Store.LatestMetrics(c.Request.Context())
	if errors.Is(err, store.ErrNotFound) {
		writeError(c, http.StatusNotFound, "not_found", "model has not been trained yet")
		return
	}
	if err != nil {
		writeError(c, http.StatusInternalServerError, "db_error", err.Error())
		return
	}
	item.Disclaimer = "Учебный прототип. Прогнозы не являются ставками или финансовой рекомендацией."
	item.DataSources = []string{
		"historical: PandaScore /csgo/matches/past (finished CS2 matches); HLTV is not used",
		"upcoming: PandaScore /csgo/matches/upcoming (demo fixtures only when no token is set)",
		"rosters: PandaScore /csgo/teams (current rosters, history kept from the first snapshot)",
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}
