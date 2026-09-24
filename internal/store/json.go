package store

import (
	"encoding/json"

	"github.com/lilberdi/cyber-predict/internal/model"
)

func decodeFeatures(raw []byte) []model.FeatureContribution {
	if len(raw) == 0 {
		return nil
	}
	var out []model.FeatureContribution
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil
	}
	return out
}
