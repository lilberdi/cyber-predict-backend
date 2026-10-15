package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/store"
	"github.com/lilberdi/cyber-predict/internal/syncjob"
)

type API struct {
	Store      *store.Store
	Sync       *syncjob.Job
	SyncSecret string
}

func NewRouter(a *API, corsOrigin string) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery(), gin.Logger(), cors(corsOrigin))

	r.GET("/health", a.Health)
	r.GET("/openapi.yaml", serveOpenAPI)
	r.GET("/swagger", func(c *gin.Context) { c.Redirect(http.StatusFound, "/swagger/") })
	r.GET("/swagger/*filepath", serveSwaggerUI)
	r.GET("/docs", func(c *gin.Context) { c.Redirect(http.StatusFound, "/swagger/") })

	v1 := r.Group("/api/v1")
	{
		matches := v1.Group("/matches")
		{
			matches.GET("/upcoming", a.ListUpcoming)
			matches.GET("/:id", a.GetMatch)
		}
		v1.GET("/predictions/:id", a.GetPrediction)
		v1.GET("/model/metrics", a.GetMetrics)
		v1.GET("/jobs/sync-upcoming", a.SyncUpcoming)
		v1.POST("/jobs/sync-upcoming", a.SyncUpcoming)
	}
	return r
}

func cors(origin string) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", origin)
		c.Header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Sync-Key")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
