package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

func (a *API) SyncUpcoming(c *gin.Context) {
	if a.Sync == nil {
		writeError(c, http.StatusServiceUnavailable, "sync_disabled", "sync job is not configured")
		return
	}
	if a.SyncSecret != "" && c.GetHeader("X-Sync-Key") != a.SyncSecret {
		writeError(c, http.StatusUnauthorized, "unauthorized", "missing or invalid X-Sync-Key")
		return
	}
	res := a.Sync.Sync(c.Request.Context())
	status := http.StatusOK
	if res.Error != "" && res.Upserted == 0 {
		status = http.StatusBadGateway
	}
	c.JSON(status, gin.H{"data": res})
}
