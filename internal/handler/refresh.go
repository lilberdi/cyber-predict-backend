package handler

import (
	"errors"
	"math"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/lilberdi/cyber-predict/internal/model"
	"github.com/lilberdi/cyber-predict/internal/store"
	"github.com/lilberdi/cyber-predict/internal/syncjob"
)

type refreshResponse struct {
	syncjob.RefreshResult
	// NewlyFinished are the matches this refresh closed (finished or voided), newest first.
	NewlyFinished []model.Match `json:"newly_finished"`
}

// RefreshMatches pulls fresh results for matches that should already have been played.
func (a *API) RefreshMatches(c *gin.Context) {
	if a.Refresher == nil {
		writeError(c, http.StatusServiceUnavailable, "refresh_disabled", "refresh is not configured")
		return
	}
	res, err := a.Refresher.Refresh(c.Request.Context())
	var cd syncjob.ErrCooldown
	switch {
	case errors.As(err, &cd):
		secs := int(math.Ceil(cd.RetryAfter.Seconds()))
		c.Header("Retry-After", strconv.Itoa(secs))
		c.JSON(http.StatusTooManyRequests, gin.H{"error": model.ErrorBody{
			Code: "cooldown", Message: "matches were refreshed a moment ago", RetryAfterSeconds: &secs,
		}})
		return
	case errors.Is(err, syncjob.ErrNoToken):
		writeError(c, http.StatusServiceUnavailable, "pandascore_not_configured", "PandaScore token is not set")
		return
	case err != nil:
		writeError(c, http.StatusBadGateway, "upstream_error", err.Error())
		return
	}

	out := refreshResponse{RefreshResult: res, NewlyFinished: []model.Match{}}
	for i := len(res.ChangedIDs) - 1; i >= 0; i-- {
		m, err := a.Store.GetMatch(c.Request.Context(), res.ChangedIDs[i])
		if err != nil {
			continue
		}
		store.MarkPredictionCorrect(&m)
		out.NewlyFinished = append(out.NewlyFinished, m)
	}
	c.JSON(http.StatusOK, gin.H{"data": out})
}
