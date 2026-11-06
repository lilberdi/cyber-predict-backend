"""Compare two training reports (metrics.json) and print a Markdown section for the weekly report.

Typical use after a retrain on fresh data:

    python -m ml ingest-past --days 30      # pull matches played since the last snapshot
    python -m ml train                      # writes ml/artifacts/metrics.json
    python -m ml compare > docs/pm/12-retrain.md

The baseline defaults to the 16.10.2026 snapshot in ml/baseline (shipped in the ml image). Live accuracy (pre-match
predictions vs real results) is read from PostgreSQL when it is reachable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ml.config import ARTIFACTS_DIR, ROOT

DEFAULT_BASELINE = ROOT / "ml" / "baseline" / "metrics-2026-10-16.json"  # inside the ml image too
DEFAULT_CURRENT = ARTIFACTS_DIR / "metrics.json"
MODELS = [("elo_only", "Elo (фаворит по рейтингу)"), ("elo_logreg", "Logistic regression"), ("elo_xgboost", "XGBoost (рабочая)")]


def _get(d: dict | None, *path, default=None):
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%".replace(".", ",")


def _num(v, digits: int = 3) -> str:
    return "—" if v is None else f"{v:.{digits}f}".replace(".", ",")


def _delta(new, old, *, pct: bool = False, lower_is_better: bool = False, digits: int = 3, plain: bool = False) -> str:
    if new is None or old is None:
        return "—"
    d = new - old
    if abs(d) < 1e-12:
        return "0"
    better = (d < 0) if lower_is_better else (d > 0)
    num = (f"{d * 100:+.1f}" if pct else f"{d:+.{digits}f}").replace(".", ",")
    text = f"{num} п.п." if pct else num
    return text if plain else f"{text} ({'лучше' if better else 'хуже'})"


def live_accuracy() -> dict | None:
    """Same rule as GET /api/v1/model/live-accuracy: only predictions stored before the start."""
    try:
        from ml.db import connect

        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS n,
                       count(*) FILTER (WHERE (p.p_team1_win >= 0.5) = (m.winner_team_id = m.team1_id)) AS ok,
                       min(m.scheduled_at) AS since, max(m.scheduled_at) AS until
                FROM matches m JOIN predictions p ON p.match_id = m.id
                WHERE m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.voided_reason IS NULL
                  AND p.created_at <= m.scheduled_at AND p.p_team1_win <> 0.5
                """
            )
            row = cur.fetchone()
            cur.execute(
                """
                SELECT COALESCE(p.confidence, 'unknown') AS conf, count(*) AS n,
                       count(*) FILTER (WHERE (p.p_team1_win >= 0.5) = (m.winner_team_id = m.team1_id)) AS ok
                FROM matches m JOIN predictions p ON p.match_id = m.id
                WHERE m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.voided_reason IS NULL
                  AND p.created_at <= m.scheduled_at AND p.p_team1_win <> 0.5
                GROUP BY 1 ORDER BY 1
                """
            )
            by_conf = {r["conf"]: (int(r["n"]), int(r["ok"])) for r in cur.fetchall()}
    except Exception as exc:  # DB is optional for the report
        return {"error": str(exc)}
    return {"evaluated": int(row["n"]), "correct": int(row["ok"]), "since": row["since"], "until": row["until"], "by_confidence": by_conf}


def render(old: dict, new: dict, live: dict | None) -> str:
    lines: list[str] = []
    od, nd = _get(old, "extra", "data", default={}), _get(new, "extra", "data", default={})
    lines += [
        f"## Переобучение на свежих данных ({datetime.now(timezone.utc):%d.%m.%Y})",
        "",
        "### Данные",
        "",
        "| | Было (16.10) | Стало | Разница |",
        "|---|---|---|---|",
        f"| Матчей в обучении | {od.get('n_matches', '—')} | {nd.get('n_matches', '—')} | "
        f"{_delta(nd.get('n_matches'), od.get('n_matches'), digits=0, plain=True) if od.get('n_matches') and nd.get('n_matches') else '—'} |",
        f"| Команд | {od.get('n_teams', '—')} | {nd.get('n_teams', '—')} | — |",
        f"| Период | {str(od.get('from', '—'))[:10]} – {str(od.get('to', '—'))[:10]} | "
        f"{str(nd.get('from', '—'))[:10]} – {str(nd.get('to', '—'))[:10]} | — |",
        f"| Тест (последние 20%) | {old.get('n_test', '—')} | {new.get('n_test', '—')} | — |",
        "",
        "### Тест: последние 20% истории",
        "",
        "| Модель | Accuracy было | Accuracy стало | Log-loss было | Log-loss стало | Brier стало |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in MODELS:
        o, n = _get(old, "extra", "comparison", key, default={}), _get(new, "extra", "comparison", key, default={})
        lines.append(
            f"| {label} | {_pct(o.get('accuracy'))} | {_pct(n.get('accuracy'))} "
            f"({_delta(n.get('accuracy'), o.get('accuracy'), pct=True)}) | {_num(o.get('log_loss'))} | "
            f"{_num(n.get('log_loss'))} ({_delta(n.get('log_loss'), o.get('log_loss'), lower_is_better=True)}) | {_num(n.get('brier'), 4)} |"
        )

    lines += ["", "### Walk-forward (5 окон)", "", "| Модель | Accuracy было | Accuracy стало | Log-loss стало |", "|---|---|---|---|"]
    for key, label in MODELS:
        o = _get(old, "extra", "walk_forward", "results", key, default={})
        n = _get(new, "extra", "walk_forward", "results", key, default={})
        oa, na = _get(o, "accuracy", "mean"), _get(n, "accuracy", "mean")
        lines.append(f"| {label} | {_pct(oa)} | {_pct(na)} ({_delta(na, oa, pct=True)}) | {_num(_get(n, 'log_loss', 'mean'))} |")

    ci = _get(new, "extra", "significance", "xgboost_minus_elo", "ci95")
    ece_old, ece_new = _get(old, "extra", "calibration", "ece"), _get(new, "extra", "calibration", "ece")
    lines += [
        "",
        "### Значимость и калибровка",
        "",
        f"- Разница accuracy XGBoost − Elo: {_delta(_get(new, 'extra', 'significance', 'xgboost_minus_elo', 'mean'), 0, pct=True, plain=True)}, "
        + (f"95% интервал {ci[0] * 100:+.1f} … {ci[1] * 100:+.1f}".replace(".", ",") + " п.п." if ci else "интервал не посчитан")
        + (" — интервал включает ноль, разница статистически не значима." if ci and ci[0] <= 0 <= ci[1] else "."),
        f"- ECE: было {_num(ece_old)}, стало {_num(ece_new)} ({_delta(ece_new, ece_old, lower_is_better=True)}); "
        f"выбранная калибровка: {_get(new, 'extra', 'calibration', 'chosen', default='—')}.",
    ]

    lines += ["", "### Проверка в бою (прогноз сохранён до начала матча)", ""]
    if not live or "error" in live:
        lines.append(f"База недоступна, блок не посчитан: {(live or {}).get('error', 'нет данных')}. Возьмите цифры из `GET /api/v1/model/live-accuracy`.")
    elif live["evaluated"] == 0:
        lines.append("Пока нет ни одного оценённого матча.")
    else:
        acc = live["correct"] / live["evaluated"]
        lines.append(
            f"С {live['since']:%d.%m.%Y} по {live['until']:%d.%m.%Y}: **{live['correct']} из {live['evaluated']}** "
            f"верных, точность **{_pct(acc)}** (на 16.10 выборки не было). Ожидание по тесту: {_pct(_get(new, 'extra', 'comparison', 'elo_xgboost', 'accuracy'))}."
        )
        if live.get("by_confidence"):
            lines += ["", "| Уверенность | Матчей | Верных | Точность |", "|---|---|---|---|"]
            for conf, (n, ok) in live["by_confidence"].items():
                lines.append(f"| {conf} | {n} | {ok} | {_pct(ok / n if n else None)} |")
    lines.append("")
    return "\n".join(lines)


def compare(baseline: Path | None = None, current: Path | None = None, out: Path | None = None, with_live: bool = True) -> str:
    old = json.loads(Path(baseline or DEFAULT_BASELINE).read_text(encoding="utf-8"))
    new = json.loads(Path(current or DEFAULT_CURRENT).read_text(encoding="utf-8"))
    text = render(old, new, live_accuracy() if with_live else None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    return text
