"""Apply pending SQL migrations in sorted filename order.

Usage:
    python db/apply_migrations.py

Tracks applied files in _schema_migrations table. Each migration runs in its own
transaction. Idempotent: safe to re-run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
TRACKING_TABLE = "_schema_migrations"


def ensure_tracking_table(conn: psycopg.Connection) -> None:  # type: ignore[type-arg]
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
            filename   TEXT        PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.commit()


def applied_migrations(conn: psycopg.Connection) -> set[str]:  # type: ignore[type-arg]
    rows = conn.execute(f"SELECT filename FROM {TRACKING_TABLE}").fetchall()
    return {row[0] for row in rows}


def run_migration(conn: psycopg.Connection, path: Path) -> None:  # type: ignore[type-arg]
    sql = path.read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)
        conn.execute(
            f"INSERT INTO {TRACKING_TABLE} (filename) VALUES (%s)",
            (path.name,),
        )
    print(f"  applied: {path.name}")


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print("No migration files found.")
        return

    with psycopg.connect(database_url) as conn:
        ensure_tracking_table(conn)
        already_applied = applied_migrations(conn)

        pending = [f for f in migration_files if f.name not in already_applied]
        if not pending:
            print("All migrations already applied.")
            return

        print(f"Applying {len(pending)} migration(s)...")
        for path in pending:
            run_migration(conn, path)

    print("Done.")


if __name__ == "__main__":
    main()
