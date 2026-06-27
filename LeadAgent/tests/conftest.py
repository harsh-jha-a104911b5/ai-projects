"""Shared pytest fixtures.

The `pg_with_schema` fixture spins up a real pgvector/pgvector:pg16 container.
Only integration-marked tests use it. Unit tests (chunker, crawler) need no DB.

Requires Docker Desktop to be running for integration tests.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
import psycopg

# psycopg3 async requires SelectorEventLoop; Windows defaults to ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from testcontainers.postgres import PostgresContainer
    _TESTCONTAINERS_AVAILABLE = True
except ImportError:
    _TESTCONTAINERS_AVAILABLE = False

# pgvector/pgvector:pg16 ships with the vector extension pre-installed.
# Do NOT substitute postgres:16-alpine — CREATE EXTENSION vector will fail.
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"


def _is_docker_available() -> bool:
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_container():
    if not _TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not installed")
    if not _is_docker_available():
        pytest.skip("Docker not available — skipping integration tests")
    with PostgresContainer(image=PGVECTOR_IMAGE, dbname="testdb") as container:
        yield container


@pytest.fixture(scope="session")
def pg_with_schema(pg_container) -> str:
    """Apply migrations to the container and return the psycopg3 connection URL."""
    # testcontainers returns a psycopg2-style URL; rewrite for psycopg3
    url = pg_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "db", "migrations")
    with psycopg.connect(url) as conn:
        for filename in sorted(os.listdir(migrations_dir)):
            if filename.endswith(".sql"):
                path = os.path.join(migrations_dir, filename)
                conn.execute(open(path).read())
        conn.commit()

    return url
