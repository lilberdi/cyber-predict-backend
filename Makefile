COMPOSE = docker compose
PYTHON ?= python3.11
export DATABASE_URL ?= postgres://cyber:cyber@localhost:55432/cyber_predict?sslmode=disable

.PHONY: up down logs api test-go tidy \
	venv install-ml sample load-history train sync predict pipeline

up:
	$(COMPOSE) up -d --build postgres
	@echo "waiting for postgres..."
	@$(COMPOSE) up -d --build api

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api

api:
	go run ./cmd/api

test-go:
	go test ./...

tidy:
	go mod tidy

venv:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r requirements.txt

install-ml:
	$(PYTHON) -m pip install -r requirements.txt

sample:
	$(PYTHON) -m ml generate-sample

load-history:
	$(PYTHON) -m ml load-history

train:
	$(PYTHON) -m ml train

sync:
	$(PYTHON) -m ml sync

predict:
	$(PYTHON) -m ml predict

pipeline: sample load-history train sync predict
	@echo "week 1-4 pipeline done"
