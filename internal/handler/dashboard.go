package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/docs"
)

// serveDashboard shows live upcoming matches with XGBoost probabilities.
func serveDashboard(c *gin.Context) {
	raw, err := docs.FS.ReadFile("dashboard/index.html")
	if err != nil {
		c.String(http.StatusInternalServerError, "dashboard missing")
		return
	}
	c.Data(http.StatusOK, "text/html; charset=utf-8", raw)
}
