# Статус-отчёт: конец недели 4

**Дата:** 2026-09-24  
**Спринт:** S2  
**Общее:** зелёный для объёма 1–4 недель.

## Сделано

- Пакет PM: устав, стейкхолдеры, RACI, MoSCoW, WBS, риски.
- Go/Gin: `/health`, `/api/v1/matches/upcoming`, `/matches/:id`, `/predictions/:id`, `/model/metrics`.
- PostgreSQL + миграции + Docker Compose.
- OpenAPI: `docs/openapi.yaml`.
- Python: sample history, load, Elo+logreg, sync (PandaScore или fixtures), predict.
- Тест на отсутствие утечки признаков.

## Блокеры

Нет. Ключ PandaScore опционален: без него используются `data/fixtures/upcoming.json`.

## Следующий спринт (недели 5–6)

XGBoost, сравнение с baseline, больше признаков (тир турнира, стабильность состава).
