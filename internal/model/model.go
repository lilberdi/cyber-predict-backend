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
	// PredictionCorrect is set only for finished matches that had a pre-match prediction.
	PredictionCorrect *bool `json:"prediction_correct,omitempty"`
}

type AccuracyBucket struct {
	Evaluated int     `json:"evaluated"`
	Correct   int     `json:"correct"`
	Accuracy  float64 `json:"accuracy"`
}

// LiveAccuracy is the track record of predictions made before the match started.
type LiveAccuracy struct {
	AccuracyBucket
	ByConfidence map[string]AccuracyBucket `json:"by_confidence"`
	ByModel      map[string]AccuracyBucket `json:"by_model"`
	Since        *time.Time                `json:"since,omitempty"`
	Note         string                    `json:"note"`
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

// Player is a rostered player with his Team Impact Rating (Elo from team results).
type Player struct {
	ID           int64      `json:"id"`
	Nickname     string     `json:"nickname"`
	Slug         *string    `json:"slug,omitempty"`
	FirstName    *string    `json:"first_name,omitempty"`
	LastName     *string    `json:"last_name,omitempty"`
	Nationality  *string    `json:"nationality,omitempty"`
	ImageURL     *string    `json:"image_url,omitempty"`
	Team         *Team      `json:"team,omitempty"`
	JoinedAt     *time.Time `json:"joined_at,omitempty"`
	Rating       *float64   `json:"rating,omitempty"`
	RatedMatches int        `json:"rated_matches"`
	RatingIsSeed bool       `json:"rating_is_seed"`
	Rank         *int       `json:"rank,omitempty"`
}

type RatingPoint struct {
	MatchID     int64     `json:"match_id"`
	PlayedAt    time.Time `json:"played_at"`
	TeamID      int64     `json:"team_id"`
	RatingAfter float64   `json:"rating_after"`
	Delta       float64   `json:"delta"`
}

type RosterStint struct {
	Team     Team       `json:"team"`
	JoinedAt time.Time  `json:"joined_at"`
	LeftAt   *time.Time `json:"left_at,omitempty"`
}

type PlayerDetail struct {
	Player
	History []RatingPoint `json:"rating_history"`
	Teams   []RosterStint `json:"teams"`
}

type TeamDetail struct {
	Team
	Elo        *float64 `json:"elo,omitempty"`
	EloMatches int      `json:"elo_matches"`
	Roster     []Player `json:"roster"`
	RosterNote string   `json:"roster_note"`
}

type Transfer struct {
	Player    Player    `json:"player"`
	Kind      string    `json:"kind"`
	FromTeam  *Team     `json:"from_team,omitempty"`
	ToTeam    *Team     `json:"to_team,omitempty"`
	ChangedAt time.Time `json:"changed_at"`
}
