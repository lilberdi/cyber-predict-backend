package model

import (
	"encoding/json"
	"time"
)

type Team struct {
	ID       int64   `json:"id"`
	Name     string  `json:"name"`
	Slug     *string `json:"slug,omitempty"`
	ImageURL *string `json:"image_url,omitempty"`
}

type Score struct {
	Team1 *int `json:"team1"`
	Team2 *int `json:"team2"`
}

type FeatureContribution struct {
	Name   string  `json:"name"`
	Value  float64 `json:"value"`
	Impact string  `json:"impact,omitempty"`
	// Contribution is the per-match SHAP value (log-odds) for XGBoost predictions.
	Contribution *float64 `json:"contribution,omitempty"`
}

type Prediction struct {
	MatchID      int64                 `json:"match_id"`
	ModelName    string                `json:"model_name"`
	ModelVersion string                `json:"model_version"`
	PTeam1Win    float64               `json:"p_team1_win"`
	PTeam2Win    float64               `json:"p_team2_win"`
	Confidence   *string               `json:"confidence,omitempty"`
	TopFeatures  []FeatureContribution `json:"top_features,omitempty"`
	Explanation  *string               `json:"explanation,omitempty"`
	CreatedAt    time.Time             `json:"created_at"`
}

type Match struct {
	ID             int64       `json:"id"`
	ExternalID     *string     `json:"external_id,omitempty"`
	Source         string      `json:"source"`
	Status         string      `json:"status"`
	BestOf         *int        `json:"best_of,omitempty"`
	ScheduledAt    *time.Time  `json:"scheduled_at,omitempty"`
	Tournament     *string     `json:"tournament,omitempty"`
	TournamentTier *string     `json:"tournament_tier,omitempty"`
	Team1          Team        `json:"team1"`
	Team2          Team        `json:"team2"`
	Score          Score       `json:"score"`
	WinnerTeamID   *int64      `json:"winner_team_id,omitempty"`
	Prediction     *Prediction `json:"prediction,omitempty"`
}

type ModelMetrics struct {
	ModelName           string          `json:"model_name"`
	ModelVersion        string          `json:"model_version"`
	TrainedAt           time.Time       `json:"trained_at"`
	NTrain              *int            `json:"n_train,omitempty"`
	NTest               *int            `json:"n_test,omitempty"`
	Accuracy            *float64        `json:"accuracy,omitempty"`
	LogLoss             *float64        `json:"log_loss,omitempty"`
	Brier               *float64        `json:"brier,omitempty"`
	EloFavoriteAccuracy *float64        `json:"elo_favorite_accuracy,omitempty"`
	Extra               json.RawMessage `json:"extra,omitempty"`
	Disclaimer          string          `json:"disclaimer"`
	DataSources         []string        `json:"data_sources"`
}

type ErrorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}
