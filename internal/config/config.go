package config

import (
	"os"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	Port            string
	DatabaseURL     string
	CORSOrigin      string
	PandaScoreToken string
	PandaScoreBase  string
	SyncInterval    string
	SyncSecret      string
	TopTeams        string
	SyncRequireBoth string
}

func Load() Config {
	_ = godotenv.Load()
	return Config{
		Port:            env("PORT", "8080"),
		DatabaseURL:     env("DATABASE_URL", "postgres://cyber:cyber@localhost:55432/cyber_predict?sslmode=disable"),
		CORSOrigin:      env("CORS_ORIGIN", "*"),
		PandaScoreToken: env("PANDASCORE_TOKEN", ""),
		PandaScoreBase:  env("PANDASCORE_BASE_URL", "https://api.pandascore.co"),
		SyncInterval:    env("SYNC_INTERVAL", "1h"),
		SyncSecret:      env("SYNC_SECRET", ""),
		TopTeams:        env("TOP_TEAMS", "60"),
		SyncRequireBoth: env("SYNC_REQUIRE_BOTH", "false"),
	}
}

func env(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}
