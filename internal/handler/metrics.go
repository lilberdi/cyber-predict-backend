package handler

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
)

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
		"historical: bundled sample CS2-style match history (replace with licensed Kaggle/HF dataset)",
		"upcoming: PandaScore /csgo/matches/upcoming or local fixtures",
	}
	c.JSON(http.StatusOK, gin.H{"data": item})
}
