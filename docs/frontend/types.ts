/**
 * Типы ответов Cyber Predict API (v1). Источник истины: docs/openapi.yaml.
 * Все ответы: { data: T } при успехе, { error: ApiError } при ошибке.
 */

export interface ApiError {
  code: 'not_found' | 'bad_request' | 'db_error' | string
  message: string
}
export interface ApiOk<T> { data: T }
export interface ApiFail { error: ApiError }

export interface Team {
  id: number
  name: string
  /** Может отсутствовать. */
  slug?: string
  /** Может отсутствовать: нужна заглушка с инициалами. */
  image_url?: string
}

export interface Score {
  /** null, пока матч не сыгран. */
  team1: number | null
  team2: number | null
}

export type Confidence = 'low' | 'medium' | 'high'
export type MatchStatus = 'upcoming' | 'running' | 'finished'
export type MatchSource = 'pandascore' | 'fixture' | 'dataset'
/** 'elo_xgboost' — основная модель; 'elo_sync' — быстрый запасной Elo-прогноз. */
export type ModelName = 'elo_xgboost' | 'elo_sync' | 'elo_logreg' | (string & {})

export type FeatureName =
  | 'elo_diff' | 'form5_diff' | 'form10_diff' | 'h2h_diff' | 'exp_diff'
  | 'best_of' | 'tier' | 'ewm_form_diff' | 'rest_diff' | 'margin_diff'

export interface FeatureContribution {
  /** Список может расшириться: неизвестное имя показывайте как есть. */
  name: FeatureName | (string & {})
  /** Значение признака (см. таблицу подписей в CONTRACT.md). */
  value: number
  impact?: 'favors_team1' | 'favors_team2'
  /** SHAP-вклад в логит. Только у elo_xgboost; знак + в пользу team1. */
  contribution?: number
}

export interface Prediction {
  match_id: number
  model_name: ModelName
  model_version: string
  /** 0..1, p_team1_win + p_team2_win = 1. */
  p_team1_win: number
  p_team2_win: number
  confidence?: Confidence
  /** До 5 элементов, по убыванию влияния. */
  top_features?: FeatureContribution[]
  /** Готовая строка на русском. */
  explanation?: string
  created_at: string // ISO 8601 с часовым поясом
}

export interface Match {
  id: number
  external_id?: string
  source: MatchSource
  status: MatchStatus
  best_of?: number
  /** ISO 8601 с часовым поясом (может быть +05:00): парсить через new Date(). */
  scheduled_at?: string
  tournament?: string
  /** 's' | 'a' | 'b' | 'c' | 'd', строчные. */
  tournament_tier?: string
  team1: Team
  team2: Team
  score: Score
  winner_team_id?: number
  /** Нет, пока прогноз не посчитан. */
  prediction?: Prediction
  /** Только в /matches/finished. */
  prediction_correct?: boolean
}

export interface AccuracyBucket {
  evaluated: number
  correct: number
  /** 0..1. Не показывать, пока evaluated < 10. */
  accuracy: number
}

export interface LiveAccuracy extends AccuracyBucket {
  by_confidence: Partial<Record<Confidence | 'unknown', AccuracyBucket>>
  by_model: Record<string, AccuracyBucket>
  /** Время самого раннего учтённого матча. */
  since?: string
  note: string
}

export interface ScoreSet { accuracy: number; log_loss: number; brier: number }

export interface ModelComparisonEntry extends ScoreSet { label: string }

export interface MeanStd { mean: number; std: number }

export interface Interval { mean: number; ci95: [number, number] }

export interface ReliabilityBin {
  /** Например "0.6-0.7". */
  bin: string
  n: number
  /** Средняя предсказанная вероятность. */
  predicted: number
  /** Доля реальных побед. */
  actual: number
}

export interface ModelMetricsExtra {
  split: string
  leakage_guard: string
  active_model: ModelName
  features: string[]
  data: {
    source: 'pandascore' | 'synthetic'
    n_matches: number
    n_teams: number
    from: string
    to: string
  }
  /** Ключи: elo_only, elo_logreg, elo_xgboost. */
  comparison: Record<string, ModelComparisonEntry>
  walk_forward: {
    folds: number
    results: Record<string, { accuracy: MeanStd; log_loss: MeanStd; brier: MeanStd }>
  }
  /** Если ci95 включает 0, преимущество не доказано. */
  significance: {
    xgboost_accuracy: Interval
    elo_accuracy: Interval
    xgboost_minus_elo: Interval
    xgboost_minus_logreg: Interval
  }
  known_teams_only: {
    min_games: number
    n: number
    elo_only: ScoreSet | null
    elo_xgboost: ScoreSet | null
  }
  /** Только в строке XGBoost. */
  feature_importance?: Record<string, number>
  xgb_params?: Record<string, number>
  ablation?: Record<string, {
    log_loss_without: number
    log_loss_gain: number
    accuracy_without: number
    accuracy_gain: number
  }>
  calibration?: {
    chosen: 'raw' | 'platt' | 'isotonic'
    ece: number
    compare: Record<string, ScoreSet & { ece: number }>
    reliability: ReliabilityBin[]
  }
}

export interface ModelMetrics {
  model_name: ModelName
  model_version: string
  trained_at: string
  n_train?: number
  n_test?: number
  accuracy?: number
  log_loss?: number
  brier?: number
  elo_favorite_accuracy?: number
  /** Может отсутствовать: обращайтесь через ?. */
  extra?: ModelMetricsExtra
  disclaimer: string
  data_sources: string[]
}

export type UpcomingResponse = ApiOk<Match[]>
export type MatchResponse = ApiOk<Match>
export type PredictionResponse = ApiOk<Prediction>
export type FinishedResponse = ApiOk<Match[]>
export type LiveAccuracyResponse = ApiOk<LiveAccuracy>
export type ModelMetricsResponse = ApiOk<ModelMetrics>

// ---- Players, rosters, transfers ----
export interface Player {
  id: number;
  nickname: string;
  slug?: string;
  first_name?: string;
  last_name?: string;
  nationality?: string; // ISO country code
  image_url?: string;
  team?: Team;
  joined_at?: string; // when we first saw him on this team, not the real join date
  rating?: number | null; // Team Impact Rating: Elo from team results, not personal stats
  rated_matches: number;
  rating_is_seed: boolean; // true: still the starting value (team Elo); show as provisional
  rank?: number;
}
export interface RatingPoint { match_id: number; played_at: string; team_id: number; rating_after: number; delta: number }
export interface RosterStint { team: Team; joined_at: string; left_at?: string | null }
export interface PlayerDetail extends Player { rating_history: RatingPoint[]; teams: RosterStint[] }
export interface TeamDetail extends Team { elo?: number | null; elo_matches: number; roster: Player[]; roster_note: string }
export interface Transfer { player: Player; kind: 'join' | 'leave' | 'transfer'; from_team?: Team; to_team?: Team; changed_at: string }
