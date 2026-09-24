package handler

import (
	"errors"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/model"
	"github.com/lilberdi/cyber-predict/internal/store"
)

type API struct {
	Store *store.Store
}

func NewRouter(a *API, corsOrigin string) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery(), gin.Logger(), cors(corsOrigin))

	r.GET("/health", a.Health)
	v1 := r.Group("/api/v1")
	{
		v1.GET("/matches/upcoming", a.ListUpcoming)
		v1.GET("/matches/:id", a.GetMatch)
		v1.GET("/predictions/:id", a.GetPrediction)
		v1.GET("/model/metrics", a.GetMetrics)
	}
	return r
}

func cors(origin string) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", origin)
		c.Header("Access-Control-Allow-Methods", "GET, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func (a *API) Health(c *gin.Context) {
	if err := a.Store.Ping(c.Request.Context()); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status": "degraded",
			"error":  err.Error(),
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func (a *API) ListUpcoming(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "50"))
	items, err := a.Store.ListUpcoming(c.Request.Context(), limit)
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

func parseID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		writeError(c, http.StatusBadRequest, "bad_request", "id must be a positive integer")
		return 0, false
	}
	return id, true
}

func writeError(c *gin.Context, status int, code, message string) {
	c.JSON(status, gin.H{"error": model.ErrorBody{Code: code, Message: message}})
}
