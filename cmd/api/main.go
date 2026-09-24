package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/lilberdi/cyber-predict/internal/config"
	"github.com/lilberdi/cyber-predict/internal/handler"
	"github.com/lilberdi/cyber-predict/internal/migrate"
	"github.com/lilberdi/cyber-predict/internal/pandascore"
	"github.com/lilberdi/cyber-predict/internal/store"
	"github.com/lilberdi/cyber-predict/internal/syncjob"
)

func main() {
	cfg := config.Load()

	migrationsPath := os.Getenv("MIGRATIONS_PATH")
	if migrationsPath == "" {
		migrationsPath = "file://migrations"
	}
	if err := migrate.Up(cfg.DatabaseURL, migrationsPath); err != nil {
		log.Fatalf("migrations: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	db, err := store.New(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("store: %v", err)
	}
	defer db.Close()

	topN, _ := strconv.Atoi(cfg.TopTeams)
	if topN <= 0 {
		topN = 60
	}
	job := &syncjob.Job{
		Store:       db,
		Client:      pandascore.New(cfg.PandaScoreBase, cfg.PandaScoreToken),
		TopN:        topN,
		RequireBoth: cfg.SyncRequireBoth != "false",
	}

	ctxRun, stopJobs := context.WithCancel(context.Background())
	defer stopJobs()
	if every, err := syncjob.ParseInterval(cfg.SyncInterval); err != nil {
		log.Printf("sync interval: %v", err)
	} else if every > 0 {
		go job.Loop(ctxRun, every)
	}

	router := handler.NewRouter(&handler.API{Store: db, Sync: job, SyncSecret: cfg.SyncSecret}, cfg.CORSOrigin)
	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           router,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("api listening on :%s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = srv.Shutdown(shutdownCtx)
}
