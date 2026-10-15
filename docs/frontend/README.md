# Cyber Predict: руководство для frontend (Vue.js)

Прогнозы матчей CS2. Бэкенд — Go/Gin REST, данные уже лежат в PostgreSQL, фронтенд только читает их по HTTP. Прогнозы учебные, не ставки.

## 1. Запуск бэкенда локально

```bash
cp .env.example .env     # один раз; PORT=18080, токен PandaScore необязателен
docker compose up -d --build
```

- API: `http://localhost:18080` (порт из `PORT` в `.env`).
- Swagger с кнопкой «Try it out»: `http://localhost:18080/swagger/`. Контракт: [docs/openapi.yaml](../openapi.yaml).
- Проверка: `curl http://localhost:18080/health` → `{"status":"ok"}`.
- Без токена PandaScore API отдаёт демо-матчи из `data/fixtures/upcoming.json` (`source: "fixture"`). С токеном — живой календарь (`source: "pandascore"`), обновляется раз в час.
- Прогнозы XGBoost считает контейнер `ml` каждые 10 минут. Сразу после первого запуска `prediction` у новых матчей может быть быстрым Elo-прогнозом (`model_name: "elo_sync"`), потом заменится на `elo_xgboost`.

**CORS.** Бэкенд разрешает запросы только с адреса из переменной `CORS_ORIGIN` в `.env` (по умолчанию `http://localhost:3000`). Vite по умолчанию работает на `5173`, поэтому либо поставьте `CORS_ORIGIN=http://localhost:5173` и перезапустите `docker compose up -d`, либо проксируйте запросы через Vite:

```js
// vite.config.js
export default {
  server: { proxy: { '/api': 'http://localhost:18080' } },
}
```

С прокси в коде используйте относительные пути (`/api/v1/...`), CORS не нужен.

## 2. Эндпоинты, которые нужны фронту

Все ответы — JSON. Успех: `{ "data": ... }`. Ошибка: `{ "error": { "code": "...", "message": "..." } }` (`not_found` 404, `bad_request` 400, `db_error` 500).

| Метод | Путь | Для какого экрана |
|---|---|---|
| GET | `/api/v1/matches/upcoming?limit=50` | Список ближайших матчей с прогнозом (1–100, по умолчанию 50) |
| GET | `/api/v1/matches/{id}` | Карточка матча |
| GET | `/api/v1/predictions/{match_id}` | Только прогноз (404, если ещё не посчитан) |
| GET | `/api/v1/model/metrics` | Страница «О модели» |
| GET | `/health` | Индикатор «API жив» |

`/api/v1/jobs/sync-upcoming` — служебный, из фронта не вызывать.

## 3. Модели данных

### Match (элемент `data` у `/matches/upcoming`, `data` у `/matches/{id}`)

```json
{
  "id": 1781,
  "external_id": "ps-1741372",
  "source": "pandascore",
  "status": "upcoming",
  "best_of": 3,
  "scheduled_at": "2026-10-16T00:00:00+05:00",
  "tournament": "Group B",
  "tournament_tier": "a",
  "team1": { "id": 20, "name": "Legacy", "slug": "legacy-48cb...", "image_url": "https://cdn-api.pandascore.co/images/team/image/133708/593px_legacy_allmode.png" },
  "team2": { "id": 8, "name": "FURIA", "slug": "furia", "image_url": "https://cdn-api.pandascore.co/..." },
  "score": { "team1": null, "team2": null },
  "prediction": { "...см. ниже..." }
}
```

| Поле | Тип | Примечание |
|---|---|---|
| `source` | `pandascore` \| `fixture` \| `dataset` | `fixture` — демо-данные; показать плашку «демо» |
| `status` | `upcoming` \| `running` \| `finished` | в списке upcoming бывает `running` |
| `best_of` | number, может отсутствовать | формат серии: BO1/3/5 |
| `scheduled_at` | ISO 8601 с часовым поясом, может отсутствовать | парсить через `new Date(...)`, показывать в локальном времени |
| `tournament`, `tournament_tier` | string, могут отсутствовать | тир: `s`, `a`, `b`, `c`, `d` (строчные) |
| `team.image_url`, `team.slug` | string, могут отсутствовать | для логотипа нужна заглушка (инициалы команды) |
| `score.team1/team2` | number или `null` | у будущих матчей `null` |
| `prediction` | объект или `null` | `null`, пока прогноз не посчитан: показывать «Прогноз считается» |

### Prediction

```json
{
  "match_id": 1781,
  "model_name": "elo_xgboost",
  "model_version": "0.2.0",
  "p_team1_win": 0.357,
  "p_team2_win": 0.643,
  "confidence": "medium",
  "top_features": [
    { "name": "elo_diff", "value": -144.487, "impact": "favors_team2", "contribution": -0.464 },
    { "name": "form10_diff", "value": -0.2, "impact": "favors_team2", "contribution": -0.078 }
  ],
  "explanation": "FURIA оценивается выше (36% для Legacy). Разница Elo -144, форма (5 матчей) -0.40.",
  "created_at": "2026-10-15T23:26:52+05:00"
}
```

| Поле | Значение |
|---|---|
| `p_team1_win`, `p_team2_win` | вероятности 0…1, в сумме 1. Проценты: `Math.round(p * 100)` |
| `confidence` | `high` / `medium` / `low`: чем дальше вероятность от 50%, тем выше. `low` также значит «мало истории у команды» |
| `model_name` | `elo_xgboost` — основная модель; `elo_sync` — быстрый Elo-прогноз, пока XGBoost не пересчитал |
| `top_features` | до 5 признаков, отсортированы по силе влияния |
| `top_features[].impact` | `favors_team1` или `favors_team2` |
| `top_features[].contribution` | вклад в логит (SHAP), знак `+` в пользу team1. Есть только у `elo_xgboost`; у `elo_sync` поля нет — рисуйте только направление |
| `explanation` | готовая строка на русском, можно выводить как есть |

### Признаки (`top_features[].name`) и подписи для интерфейса

| `name` | Подпись | Что означает `value` |
|---|---|---|
| `elo_diff` | Разница рейтинга Elo | рейтинг team1 минус team2 (положительно — сильнее team1) |
| `form5_diff` | Форма (5 матчей) | разница винрейта, от −1 до 1 |
| `form10_diff` | Форма (10 матчей) | то же за 10 матчей |
| `h2h_diff` | Личные встречи (12 мес.) | от −0.5 до 0.5, 0 — встреч не было |
| `exp_diff` | Опыт (число матчей) | разница числа матчей в истории |
| `best_of` | Формат серии | 1, 3 или 5 |
| `tier` | Тир турнира | 4=S, 3=A, 2=B, 1=C, 0=D |

Для неизвестного `name` выводите сам `name` — список признаков может расшириться.

### ModelMetrics (`/api/v1/model/metrics`)

```json
{
  "model_name": "elo_xgboost", "model_version": "0.2.0",
  "trained_at": "2026-10-15T23:26:51+05:00",
  "n_train": 720, "n_test": 180,
  "accuracy": 0.617, "log_loss": 0.660, "brier": 0.234,
  "elo_favorite_accuracy": 0.644,
  "extra": {
    "split": "chronological_80_20",
    "active_model": "elo_xgboost",
    "features": ["elo_diff", "form5_diff", "form10_diff", "h2h_diff", "exp_diff", "best_of", "tier"],
    "comparison": {
      "elo_only":    { "label": "Elo (правило фаворита)", "accuracy": 0.644, "log_loss": 0.662, "brier": 0.233 },
      "elo_logreg":  { "label": "Logistic regression",    "accuracy": 0.628, "log_loss": 0.658, "brier": 0.231 },
      "elo_xgboost": { "label": "XGBoost",                "accuracy": 0.617, "log_loss": 0.660, "brier": 0.234 }
    },
    "feature_importance": { "elo_diff": 0.33, "form10_diff": 0.16, "form5_diff": 0.13, "h2h_diff": 0.13, "tier": 0.09, "exp_diff": 0.08, "best_of": 0.08 }
  },
  "disclaimer": "Учебный прототип. Прогнозы не являются ставками или финансовой рекомендацией.",
  "data_sources": ["historical: ...", "upcoming: ..."]
}
```

- `comparison` — три модели на одном тесте: удобно для столбчатой диаграммы.
- `feature_importance` — доли, в сумме 1: для горизонтальных полос.
- `extra` может отсутствовать, если модель ещё не обучалась: обрабатывайте `?.`.
- Ответ 404 `not_found` значит «модель не обучена» — показать заглушку.

## 4. Рекомендуемые экраны

1. **Список матчей** (`/`): карточка на матч: логотипы и названия команд, время и турнир, BO, полоса вероятности из двух цветов с процентами, бейджи «уверенность» и «live/демо», кнопка «Почему такой прогноз». Фильтры: поиск по команде или турниру, уверенность, сортировка по времени или по перевесу (`|p − 0.5|`). Автообновление раз в минуту.
2. **Карточка матча** (`/match/:id`): крупная полоса вероятности, `explanation`, список `top_features` как расходящиеся полосы от центра (влево — team1, вправо — team2, длина по `|contribution|`), подпись «Вклад признака в вероятность (SHAP)».
3. **О модели** (`/about`): метрики, сравнение моделей, важность признаков, дисклеймер, источники данных, честная пометка: история для обучения пока синтетическая, поэтому XGBoost не лучше Elo.
4. **Футер на всех страницах:** дисклеймер из `/model/metrics` (или константа «Учебный прототип, не ставки»).

Состояния, которые нужно обработать на каждом экране: загрузка, пустой список (календарь может быть пуст), ошибка сети/API (кнопка «Повторить»), `prediction: null`.

## 5. Пример кода (Vue 3 + fetch)

```js
// src/api.js
const BASE = import.meta.env.VITE_API_URL ?? '' // пусто при прокси Vite

async function get(path) {
  const res = await fetch(`${BASE}/api/v1${path}`)
  const body = await res.json()
  if (!res.ok) throw new Error(body.error?.message ?? res.statusText)
  return body.data
}

export const getUpcoming = (limit = 50) => get(`/matches/upcoming?limit=${limit}`)
export const getMatch = (id) => get(`/matches/${id}`)
export const getMetrics = () => get('/model/metrics')
```

```vue
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getUpcoming } from './api'

const matches = ref([])
const error = ref('')
let timer

async function load() {
  try { matches.value = await getUpcoming(); error.value = '' }
  catch (e) { error.value = e.message }
}
onMounted(() => { load(); timer = setInterval(load, 60_000) })
onUnmounted(() => clearInterval(timer))

const pct = (p) => Math.round(p * 100)
</script>
```

Для `.env` фронта: `VITE_API_URL=http://localhost:18080` (без прокси) — тогда нужен `CORS_ORIGIN=http://localhost:5173` на бэкенде.

## 6. Рекомендованный стек и структура

Vue 3 + Vite, Vue Router, Pinia (по желанию), Chart-библиотека на выбор (Chart.js / ECharts) или чистые CSS-полосы: для вероятностей и SHAP хватает `div` с шириной в процентах.

```
src/
  api.js                  # запросы
  views/MatchList.vue  MatchDetail.vue  About.vue
  components/ProbabilityBar.vue  FeatureBars.vue  TeamLogo.vue  ConfidenceBadge.vue
  utils/format.js         # проценты, время, подписи признаков
```

Цвета: team1 и team2 разными цветами (например синий и оранжевый), полоса вероятности и SHAP-полосы используют те же цвета, чтобы читалось без легенды.

## 7. Чего не делать

- Не ходить в PandaScore напрямую и не хранить токены во фронте: все данные отдаёт наш API.
- Не показывать вероятности как «ставки» или советы: везде дисклеймер.
- Не считать прогнозы на клиенте: `prediction` приходит готовым.
- Не полагаться на порядок полей и наличие необязательных полей (см. таблицу Match).

## 8. Вопросы по API

Контракт и примеры ответов: Swagger (`/swagger/`). Что менять в контракте — в [docs/openapi.yaml](../openapi.yaml). Логика модели и признаков: [отчёт по этапу S3](../pm/08-otchet-etap-s3-xgboost.md).
