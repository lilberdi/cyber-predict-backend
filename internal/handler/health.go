package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

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
