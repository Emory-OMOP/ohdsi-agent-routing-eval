"""Tests for cohort materialization to results.cohort.

Uses a DuckDB file with the results schema created in fixtures.
Materialization tests use synthetic SQL segments that mimic CIRCE
output structure but use inline VALUES, so no CDM/vocab tables needed.
"""

import json
from pathlib import Path

import duckdb
import pytest

from circe_compiler.mcp.db import next_cohort_definition_id
from circe_compiler.mcp.server import (
    _materialize_cohort,
    _resolve_cohort_json,
    compile_cohort,
)


@pytest.fixture
def results_db(tmp_path):
    """Create a DuckDB file with results schema and tables."""
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute("CREATE SCHEMA results")
    conn.execute("""
        CREATE TABLE results.cohort (
            cohort_definition_id INTEGER NOT NULL,
            subject_id BIGINT NOT NULL,
            cohort_start_date DATE NOT NULL,
            cohort_end_date DATE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE results.cohort_generation (
            cohort_definition_id INTEGER NOT NULL,
            cohort_name VARCHAR,
            source_type VARCHAR,
            source_identifier VARCHAR,
            generated_at TIMESTAMP,
            subject_count INTEGER,
            status VARCHAR
        )
    """)
    conn.close()
    return db_path


def _synthetic_segments(cohort_definition_id: int = 1) -> list[str]:
    """Build synthetic SQL segments mimicking CIRCE compiler output.

    Uses inline VALUES instead of querying CDM/vocab tables, so the
    segments can execute against a bare DuckDB with only results schema.
    """
    return [
        # Segment 1: codeset build (CREATE TEMP TABLE)
        (
            "-- [CIRCE:segment=codeset_build]\n"
            "CREATE TEMP TABLE codesets AS\n"
            "SELECT * FROM (VALUES (0, 201826), (0, 443238)) "
            "AS t(codeset_id, concept_id)"
        ),
        # Segment 2: primary events (CREATE TEMP TABLE)
        (
            "-- [CIRCE:segment=primary_events]\n"
            "CREATE TEMP TABLE primary_events AS\n"
            "SELECT * FROM (VALUES "
            "(1001, DATE '2020-03-15', DATE '2020-03-15', 0), "
            "(1002, DATE '2021-06-20', DATE '2021-06-20', 0), "
            "(1003, DATE '2019-11-01', DATE '2019-11-01', 0)"
            ") AS t(person_id, start_date, end_date, op_id)"
        ),
        # Segment 3: final INSERT INTO results.cohort
        (
            f"-- [CIRCE:segment=final_cohort]\n"
            f"INSERT INTO results.cohort\n"
            f"SELECT {cohort_definition_id} AS cohort_definition_id, "
            f"person_id AS subject_id, "
            f"start_date AS cohort_start_date, "
            f"end_date AS cohort_end_date "
            f"FROM primary_events"
        ),
    ]


# ─── next_cohort_definition_id ───────────────────────────────────────────


def test_next_id_empty_table(results_db):
    """Empty cohort table returns ID 1."""
    conn = duckdb.connect(results_db, read_only=False)
    try:
        assert next_cohort_definition_id(conn) == 1
    finally:
        conn.close()


def test_next_id_with_existing_rows(results_db):
    """Returns MAX + 1 when rows exist."""
    conn = duckdb.connect(results_db, read_only=False)
    try:
        conn.execute(
            "INSERT INTO results.cohort VALUES (5, 100, '2020-01-01', '2020-12-31')"
        )
        assert next_cohort_definition_id(conn) == 6

        conn.execute(
            "INSERT INTO results.cohort VALUES (3, 200, '2020-01-01', '2020-12-31')"
        )
        # Still 6 because MAX is 5
        assert next_cohort_definition_id(conn) == 6

        conn.execute(
            "INSERT INTO results.cohort VALUES (10, 300, '2020-01-01', '2020-12-31')"
        )
        assert next_cohort_definition_id(conn) == 11
    finally:
        conn.close()


# ─── _materialize_cohort ─────────────────────────────────────────────────


def test_materialize_returns_summary_not_rows(results_db):
    """Materialization returns summary stats, not patient-level data."""
    result = _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        db_path=results_db,
    )

    assert result["status"] == "COMPLETE"
    assert result["cohort_definition_id"] == 1
    assert result["subject_count"] == 3
    assert result["row_count"] == 3
    # Must NOT contain individual rows
    assert "rows" not in result
    assert "result" not in result


def test_materialize_writes_to_cohort_table(results_db):
    """After materialization, data exists in results.cohort."""
    result = _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        db_path=results_db,
    )

    assert result["status"] == "COMPLETE"

    # Verify data in the table
    conn = duckdb.connect(results_db, read_only=True)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM results.cohort WHERE cohort_definition_id = 1"
        ).fetchone()[0]
        assert count == result["row_count"]
        assert count == 3
    finally:
        conn.close()


def test_materialize_regeneration_replaces_rows(results_db):
    """Running materialization twice with the same ID replaces previous rows."""
    segments = _synthetic_segments(cohort_definition_id=1)

    # First run
    result1 = _materialize_cohort(
        segments=segments,
        cohort_definition_id=1,
        db_path=results_db,
    )
    assert result1["status"] == "COMPLETE"
    assert result1["row_count"] == 3

    # Second run with same ID — should replace, not append
    result2 = _materialize_cohort(
        segments=segments,
        cohort_definition_id=1,
        db_path=results_db,
    )
    assert result2["status"] == "COMPLETE"
    assert result2["row_count"] == 3  # Same count, not doubled (6)

    # Verify in DB
    conn = duckdb.connect(results_db, read_only=True)
    try:
        actual = conn.execute(
            "SELECT COUNT(*) FROM results.cohort WHERE cohort_definition_id = 1"
        ).fetchone()[0]
        assert actual == 3
    finally:
        conn.close()


def test_materialize_different_ids_coexist(results_db):
    """Different cohort_definition_ids coexist in the table."""
    _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        db_path=results_db,
    )
    _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=2),
        cohort_definition_id=2,
        db_path=results_db,
    )

    conn = duckdb.connect(results_db, read_only=True)
    try:
        ids = conn.execute(
            "SELECT DISTINCT cohort_definition_id FROM results.cohort ORDER BY 1"
        ).fetchall()
        assert [r[0] for r in ids] == [1, 2]

        # Each should have 3 rows
        for cid in [1, 2]:
            count = conn.execute(
                f"SELECT COUNT(*) FROM results.cohort WHERE cohort_definition_id = {cid}"
            ).fetchone()[0]
            assert count == 3
    finally:
        conn.close()


def test_materialize_writes_cohort_generation(results_db):
    """Materialization writes metadata to cohort_generation."""
    _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        cohort_name="Test Cohort",
        source_identifier="test-288",
        db_path=results_db,
    )

    conn = duckdb.connect(results_db, read_only=True)
    try:
        row = conn.execute(
            "SELECT cohort_name, source_type, source_identifier, status "
            "FROM results.cohort_generation WHERE cohort_definition_id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "Test Cohort"
        assert row[1] == "circe-compiler"
        assert row[2] == "test-288"
        assert row[3] == "COMPLETE"
    finally:
        conn.close()


def test_materialize_has_date_ranges(results_db):
    """Summary includes cohort date ranges when data exists."""
    result = _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        db_path=results_db,
    )

    assert result["status"] == "COMPLETE"
    assert result["subject_count"] == 3
    assert "cohort_start_date_range" in result
    assert "cohort_end_date_range" in result
    assert len(result["cohort_start_date_range"]) == 2
    # Dates span 2019-11-01 to 2021-06-20
    assert result["cohort_start_date_range"][0] == "2019-11-01"
    assert result["cohort_start_date_range"][1] == "2021-06-20"


def test_materialize_regeneration_updates_cohort_generation(results_db):
    """Re-running materialization with same ID updates cohort_generation."""
    _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        cohort_name="First Run",
        db_path=results_db,
    )
    _materialize_cohort(
        segments=_synthetic_segments(cohort_definition_id=1),
        cohort_definition_id=1,
        cohort_name="Second Run",
        db_path=results_db,
    )

    conn = duckdb.connect(results_db, read_only=True)
    try:
        rows = conn.execute(
            "SELECT cohort_name FROM results.cohort_generation "
            "WHERE cohort_definition_id = 1"
        ).fetchall()
        # Should have exactly one row (upsert), not two
        assert len(rows) == 1
        assert rows[0][0] == "Second Run"
    finally:
        conn.close()


# ─── Error handling ──────────────────────────────────────────────────────


def test_materialize_db_not_found():
    """Returns error when DB file doesn't exist."""
    result = _materialize_cohort(
        segments=["SELECT 1"],
        cohort_definition_id=1,
        db_path="/nonexistent/path/test.duckdb",
    )

    assert result["status"] == "FAILED"
    assert "error" in result
    assert "not found" in result["error"]


def test_materialize_invalid_sql_rolls_back(results_db):
    """Invalid SQL in a segment triggers rollback — no partial data."""
    bad_segments = [
        "CREATE TEMP TABLE codesets AS SELECT 1 AS codeset_id, 201826 AS concept_id",
        "THIS IS NOT VALID SQL",
        "INSERT INTO results.cohort SELECT 1, 1001, DATE '2020-01-01', DATE '2020-12-31'",
    ]

    result = _materialize_cohort(
        segments=bad_segments,
        cohort_definition_id=1,
        db_path=results_db,
    )

    assert result["status"] == "FAILED"

    # Verify no partial data was left behind
    conn = duckdb.connect(results_db, read_only=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM results.cohort").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


# ─── Integration: compile + materialize (compilation only, no CDM) ───────


def test_phenotype_288_compiles_with_assigned_id():
    """Phenotype 288 compiles successfully with a custom cohort_definition_id.

    This tests that the ID is baked into the final INSERT SQL correctly.
    Does NOT execute against a DB (no CDM tables available in tests).
    """
    resolved_json = _resolve_cohort_json(phenotype_id=288)
    result = compile_cohort(
        resolved_json, dialect="duckdb",
        cohort_definition_id=42,
    )
    assert result["success"] is True

    # The final segment should reference cohort_definition_id 42
    final_segment = result["segments"][-1]
    assert "42" in final_segment
    assert "cohort_definition_id" in final_segment.lower()
