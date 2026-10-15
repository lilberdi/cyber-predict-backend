from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.config import SAMPLE_MATCHES_PATH
from ml.db import connect, upsert_team
from ml.generate_sample import write as write_sample


def load_csv(path: Path | None = None) -> int:
    src = path or SAMPLE_MATCHES_PATH
    if not src.exists():
        write_sample(src)
    df = pd.read_csv(src)
    required = {"match_id", "played_at", "team1", "team2", "score1", "score2", "winner"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"history CSV missing columns: {sorted(missing)}")

    inserted = 0
    with connect() as conn:
        with conn.cursor() as cur:
            for row in df.itertuples(index=False):
                t1 = upsert_team(cur, str(row.team1))
                t2 = upsert_team(cur, str(row.team2))
                winner_name = str(row.winner)
                winner_id = t1 if winner_name == str(row.team1) else t2
                best_of = int(getattr(row, "best_of", 3) or 3)
                tournament = getattr(row, "tournament", None)
                tier = getattr(row, "tournament_tier", None)
                cur.execute(
                    """
                    INSERT INTO matches (
                        external_id, source, team1_id, team2_id, tournament, tournament_tier,
                        best_of, scheduled_at, status, score1, score2, winner_team_id
                    )
                    VALUES (%s, 'dataset', %s, %s, %s, %s, %s, %s, 'finished', %s, %s, %s)
                    ON CONFLICT (external_id) DO UPDATE
                        SET score1 = EXCLUDED.score1,
                            score2 = EXCLUDED.score2,
                            winner_team_id = EXCLUDED.winner_team_id,
                            status = 'finished',
                            updated_at = now()
                    """,
                    (
                        str(row.match_id),
                        t1,
                        t2,
                        None if pd.isna(tournament) else str(tournament),
                        None if pd.isna(tier) else str(tier),
                        best_of,
                        pd.Timestamp(row.played_at).to_pydatetime(),
                        int(row.score1),
                        int(row.score2),
                        winner_id,
                    ),
                )
                inserted += 1
        conn.commit()
    return inserted


MIN_REAL_MATCHES = 500


def finished_matches_frame(source: str | None = None) -> pd.DataFrame:
    """Finished matches for training. Real PandaScore history wins over the synthetic sample."""
    with connect() as conn:
        with conn.cursor() as cur:
            if source is None:
                cur.execute("SELECT count(*) AS n FROM matches WHERE status='finished' AND source='pandascore'")
                source = "pandascore" if cur.fetchone()["n"] >= MIN_REAL_MATCHES else "dataset"
            cur.execute(
                """
                SELECT m.external_id AS match_id,
                       m.scheduled_at AS played_at,
                       t1.name AS team1,
                       t2.name AS team2,
                       m.score1, m.score2, m.best_of,
                       m.tournament, m.tournament_tier,
                       tw.name AS winner
                FROM matches m
                JOIN teams t1 ON t1.id = m.team1_id
                JOIN teams t2 ON t2.id = m.team2_id
                JOIN teams tw ON tw.id = m.winner_team_id
                WHERE m.status = 'finished' AND m.winner_team_id IS NOT NULL AND m.source = %s
                ORDER BY m.scheduled_at
                """,
                (source,),
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)
