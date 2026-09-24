# Источники данных

HLTV.org **не используется**. В их Terms of Service (п. 2.2) запрещены data mining, web scraping и создание похожего сервиса.

## История для обучения

По умолчанию `python -m ml generate-sample` пишет синтетический, но Elo-согласованный календарь в `data/sample_matches.csv` (знакомые составы CS2, исходы симулированы). Это достаточно для недель 3–4 и офлайн-защиты.

Чтобы заменить на реальный открытый датасет:

1. Скачайте licensed набор (Kaggle / Hugging Face, например CounterQuant CS2 Silver, CC BY 4.0).
2. Приведите к колонкам `match_id,played_at,team1,team2,score1,score2,winner,best_of,tournament,tournament_tier`.
3. `python -m ml load-history --path path/to/file.csv`

Укажите лицензию и авторов датасета в README и на странице `/about`.

## Предстоящие матчи

- Основной канал: [PandaScore](https://developers.pandascore.co/) `GET /csgo/matches/upcoming?filter[videogame_title]=13`.
- Ключ: [app.pandascore.co/signup](https://app.pandascore.co/signup), переменная `PANDASCORE_TOKEN`.
- Фолбэк: `data/fixtures/upcoming.json`.
