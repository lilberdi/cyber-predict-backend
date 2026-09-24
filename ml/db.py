from __future__ import annotations

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from ml.config import DATABASE_URL


@contextmanager
def connect():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def upsert_team(
    cur,
    name: str,
    *,
    external_id: str | None = None,
    slug: str | None = None,
    image_url: str | None = None,
) -> int:
    if external_id:
        cur.execute(
            """
            INSERT INTO teams (external_id, name, slug, image_url)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (external_id) DO UPDATE
                SET name = EXCLUDED.name,
                    slug = COALESCE(EXCLUDED.slug, teams.slug),
                    image_url = COALESCE(EXCLUDED.image_url, teams.image_url)
            RETURNING id
            """,
            (external_id, name, slug, image_url),
        )
        return int(cur.fetchone()["id"])

    cur.execute("SELECT id FROM teams WHERE lower(name) = lower(%s)", (name,))
    found = cur.fetchone()
    if found:
        return int(found["id"])

    cur.execute(
        """
        INSERT INTO teams (name, slug, image_url)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (name, slug, image_url),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur.execute("SELECT id FROM teams WHERE lower(name) = lower(%s)", (name,))
    return int(cur.fetchone()["id"])
