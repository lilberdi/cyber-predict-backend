package store

import (
	"fmt"
	"math"
	"time"

	"github.com/lilberdi/cyber-predict/internal/model"
)

type liveRow struct {
	model, confidence, tier string
	p                       float64 // probability that team 1 wins
	team1Won                bool
	at                      *time.Time
}

// scoreLive aggregates pre-match predictions that already have a result. Rows must be ordered by time.
func scoreLive(rows []liveRow) model.LiveAccuracy {
	out := model.LiveAccuracy{
		ByConfidence: map[string]model.AccuracyBucket{},
		ByModel:      map[string]model.AccuracyBucket{},
		ByTier:       map[string]model.AccuracyBucket{},
		Reliability:  []model.ReliabilityBin{},
		Timeline:     []model.AccuracyPoint{},
		Note:         "Only predictions stored before the match start are counted; exact 50/50 calls are excluded.",
	}
	add := func(b model.AccuracyBucket, ok bool) model.AccuracyBucket {
		b.Evaluated++
		if ok {
			b.Correct++
		}
		b.Accuracy = float64(b.Correct) / float64(b.Evaluated)
		return b
	}

	const eps = 1e-6
	type bin struct {
		n         int
		pred, win float64
	}
	var bins [5]bin // favorite probability 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0
	var logLoss, brier float64
	var timeline []model.AccuracyPoint

	for _, r := range rows {
		ok := (r.p >= 0.5) == r.team1Won
		out.AccuracyBucket = add(out.AccuracyBucket, ok)
		out.ByConfidence[r.confidence] = add(out.ByConfidence[r.confidence], ok)
		out.ByModel[r.model] = add(out.ByModel[r.model], ok)
		out.ByTier[r.tier] = add(out.ByTier[r.tier], ok)

		y := 0.0
		if r.team1Won {
			y = 1
		}
		p := math.Min(math.Max(r.p, eps), 1-eps)
		logLoss += -(y*math.Log(p) + (1-y)*math.Log(1-p))
		brier += (r.p - y) * (r.p - y)

		fav := math.Max(r.p, 1-r.p)
		i := int((fav - 0.5) * 10)
		if i > 4 {
			i = 4
		}
		bins[i].n++
		bins[i].pred += fav
		if ok {
			bins[i].win++
		}

		if r.at != nil {
			if out.Since == nil || r.at.Before(*out.Since) {
				out.Since = r.at
			}
			day := r.at.UTC().Format("2006-01-02")
			pt := model.AccuracyPoint{Date: day, Evaluated: out.Evaluated, Correct: out.Correct, Accuracy: out.Accuracy}
			if n := len(timeline); n > 0 && timeline[n-1].Date == day {
				timeline[n-1] = pt
			} else {
				timeline = append(timeline, pt)
			}
		}
	}

	if n := float64(len(rows)); n > 0 {
		out.LogLoss = logLoss / n
		out.Brier = brier / n
	}
	for i, b := range bins {
		if b.n == 0 {
			continue
		}
		out.Reliability = append(out.Reliability, model.ReliabilityBin{
			Bin:       fmt.Sprintf("%.1f-%.1f", 0.5+float64(i)/10, 0.6+float64(i)/10),
			N:         b.n,
			Predicted: b.pred / float64(b.n),
			Actual:    b.win / float64(b.n),
		})
	}
	if timeline != nil {
		out.Timeline = timeline
	}
	return out
}
