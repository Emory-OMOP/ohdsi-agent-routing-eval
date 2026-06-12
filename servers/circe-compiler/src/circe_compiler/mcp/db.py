"""Read-write DuckDB connection for cohort materialization.

NO schema/table creation DDL — the results schema and tables are created
via a one-time setup script, not at runtime.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import duckdb

logger = logging.getLogger(__name__)


def get_db_path() -> str:
    """Return the path to the OHDSI DuckDB database.

    Checks OHDSI_DUCKDB_PATH env var first, then falls back to the
    repo-relative path (same parents[4] pattern used in server.py).
    """
    env_path = os.environ.get("OHDSI_DUCKDB_PATH")
    if env_path:
        return env_path
    # db.py is at servers/circe-compiler/src/circe_compiler/mcp/db.py
    # parents[5] is the repo root (set OHDSI_DUCKDB_PATH to avoid relying on this).
    repo_root = Path(__file__).resolve().parents[5]
    return str(repo_root / "synthea_omop_etl.duckdb")


@contextmanager
def get_rw_connection(
    db_path: str | None = None,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open a read-write DuckDB connection with retry logic.

    DuckDB supports only a single writer at a time. Retries up to 3 times
    with exponential backoff if the database is locked.

    Args:
        db_path: Override path to the DuckDB file. If None, uses get_db_path().

    Yields:
        An open DuckDB connection.

    Raises:
        FileNotFoundError: If the database file does not exist.
        duckdb.IOException: If the connection fails after retries.
    """
    if db_path is None:
        db_path = get_db_path()

    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {db_path}. "
            "Run the one-time setup script to create it."
        )

    max_retries = 3
    conn = None
    for attempt in range(max_retries):
        try:
            conn = duckdb.connect(db_path, read_only=False)
            break
        except duckdb.IOException as e:
            if attempt < max_retries - 1:
                wait = 0.5 * (2 ** attempt)
                logger.warning(
                    "DuckDB write lock contention (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    attempt + 1, max_retries, wait, e,
                )
                time.sleep(wait)
            else:
                raise

    try:
        yield conn  # type: ignore[arg-type]
    finally:
        if conn is not None:
            conn.close()


def next_cohort_definition_id(
    conn: duckdb.DuckDBPyConnection,
    schema: str = "results",
) -> int:
    """Return the next available cohort_definition_id.

    Uses MAX + 1 from the cohort table, defaulting to 1 if empty.
    """
    row = conn.execute(
        f"SELECT COALESCE(MAX(cohort_definition_id), 0) + 1 "
        f"FROM {schema}.cohort"
    ).fetchone()
    return row[0] if row else 1
