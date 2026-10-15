# Cyber Predict (backend)

Учебный прототип прогнозов матчей **CS2**. Публичный API — **Go/Gin**, модель — **Python**, граница — **PostgreSQL**.

Прогнозы учебные, не ставки. **HLTV не парсим** (ToS п. 2.2). Календарь upcoming — [PandaScore](https://developers.pandascore.co/) или локальные фикстуры. Подробности: [data/ATTRIBUTION.md](data/ATTRIBUTION.md).

Документы дисциплины «Управление проектами»: [docs/pm](docs/pm). Отчёт на защиту: [docs/pm/07-otchet-na-zashchitu.md](docs/pm/07-otchet-na-zashchitu.md). Для фронтенда: [docs/frontend/README.md](docs/frontend/README.md). Интерактивный контракт: **Swagger UI** `/swagger/` (спека [docs/openapi.yaml](docs/openapi.yaml)).

## Модель XGBoost

Обучение идёт на реальной истории PandaScore: `python -m ml ingest-past` (≈10 тыс. матчей, 2 минуты), затем `make train`. Отчёт с метриками: [docs/pm/09-otchet-realnye-dannye.md](docs/pm/09-otchet-realnye-dannye.md). Прод-модель — **XGBoost** (`make train` обучает также logreg и Elo как baseline и сравнивает их). Прогнозы с SHAP-объяснением отдаёт `GET /api/v1/matches/upcoming`; `docker compose up` поднимает `ml`-воркер, пересчитывающий прогнозы каждые 10 минут. Фронтенд (Vue) живёт отдельно и ходит в этот API (`CORS_ORIGIN`).

## Что готово (недели 1–4)

- Схема БД, миграции, Docker Compose (`api` + `postgres`).
- REST для upcoming / карточки матча / прогноза / метрик модели + Swagger по группам.
- Календарь PandaScore: `GET/POST /api/v1/jobs/sync-upcoming` и тикер раз в час, фильтр топ-60 команд.
- Baseline: Elo + логистическая регрессия (хронологический split, без утечки post-match статы).
- `python -m ml sync` — PandaScore или `data/fixtures/upcoming.json`.

Ещё не делали (недели 5+): реальный датасет, тир турнира и состав, полноценный фронтенд, полноценная репетиция защиты.

## Быстрый старт

Нужны Docker, Go 1.23+, Python 3.11+. Порт API задаётся в `.env` (`PORT`, по умолчанию 18080). Postgres на хосте — **55432**. После смены `.env` нужен `docker compose up -d` или перезапуск `go run` — живой процесс файл сам не читает.

```bash
cp .env.example .env
docker compose up -d --build

python3.11 -m pip install -r requirements.txt
python3.11 -m ml generate-sample
python3.11 -m ml load-history
python3.11 -m ml train
python3.11 -m ml sync
python3.11 -m ml predict
```

Проверка:

```bash
open http://localhost:${PORT:-8082}/swagger/
curl -s localhost:${PORT:-8082}/health
curl -s localhost:${PORT:-8082}/api/v1/matches/upcoming
curl -s localhost:${PORT:-8082}/api/v1/model/metrics
```

Живой календарь: зарегистрируйтесь на [app.pandascore.co](https://app.pandascore.co/signup) и положите токен в `PANDASCORE_TOKEN`. Без токена sync берёт фикстуры.

## Команды

| Команда | Смысл |
|---|---|
| `make up` | Postgres + Gin |
| `python -m ml train` | Обучить baseline, записать метрики и Elo |
| `python -m ml sync` | Upcoming → БД |
| `python -m ml predict` | Прогнозы → БД |
| `go test ./...` | Тесты API |
| `pytest tests` | Тесты признаков / Elo |

## Архитектура

```
sample CSV / licensed dataset  →  ml.load-history  →  PostgreSQL
PandaScore or fixtures         →  ml.sync          →  PostgreSQL
PostgreSQL history             →  ml.train         →  artifacts + model_metrics
upcoming rows                  →  ml.predict       →  predictions
PostgreSQL                     →  Go/Gin           →  frontend (позже)
```
