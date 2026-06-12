"""End-to-end pipeline tests for the model-as-data-bus elimination.

Tests the two one-call paths:
  Path A: phenotype_id → resolve → compile → CTE rewrite → (mock) execute
  Path B: build spec → compile → CTE rewrite → (mock) execute
"""

import json
from pathlib import Path

import pytest

from circe_compiler.mcp.server import (
    _resolve_cohort_json,
    _rewrite_as_cte_select,
    compile_cohort,
    build_cohort,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
BUILDER_SPECS_DIR = FIXTURE_DIR / "builder_specs"


def load_builder_spec(name: str) -> dict:
    with open(BUILDER_SPECS_DIR / name) as f:
        return json.load(f)


# ─── Path A: phenotype_id → compile → execute ───────────────────────────


def test_path_a_resolve_and_compile():
    """Phenotype ID 288 resolves from disk and compiles successfully."""
    resolved_json = _resolve_cohort_json(phenotype_id=288)
    result = compile_cohort(resolved_json, dialect="duckdb")

    assert result["success"] is True
    assert result["sql"]
    assert len(result["segments"]) > 0


def test_path_a_cte_rewrite():
    """Phenotype ID 288 → compile → CTE rewrite produces valid SELECT."""
    resolved_json = _resolve_cohort_json(phenotype_id=288)
    result = compile_cohort(resolved_json, dialect="duckdb")
    assert result["success"] is True

    rewritten = _rewrite_as_cte_select(result["segments"])

    upper = rewritten.upper()
    assert rewritten.strip().upper().startswith("WITH ")
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper
    assert "SELECT" in upper


def test_path_a_full_chain_cte_rewrite_produces_select():
    """Phenotype 288 → compile → CTE rewrite produces executable SELECT.

    Verifies the CTE rewrite path (used by cohort_dry_run) still works.
    The execute=True path now uses _materialize_cohort instead.
    """
    resolved_json = _resolve_cohort_json(phenotype_id=288)
    result = compile_cohort(resolved_json, dialect="duckdb")
    assert result["success"] is True

    executable_sql = _rewrite_as_cte_select(result["segments"])

    # Should be a valid CTE-based SELECT
    upper = executable_sql.upper()
    assert upper.strip().startswith("WITH ")
    assert "SELECT" in upper
    assert "INSERT INTO" not in upper
    assert "CREATE TEMP TABLE" not in upper


# ─── Path B: build spec → compile → execute ─────────────────────────────


def test_path_b_build_and_compile():
    """Build T2DM spec → compile produces valid SQL."""
    spec = load_builder_spec("t2dm_full.json")
    build_result = build_cohort(spec)
    assert build_result["success"] is True

    compile_result = compile_cohort(
        build_result["cohort_json"], dialect="duckdb"
    )
    assert compile_result["success"] is True
    assert compile_result["sql"]


def test_path_b_cte_rewrite():
    """Build T2DM spec → compile → CTE rewrite produces valid SELECT."""
    spec = load_builder_spec("t2dm_full.json")
    build_result = build_cohort(spec)
    assert build_result["success"] is True

    compile_result = compile_cohort(
        build_result["cohort_json"], dialect="duckdb"
    )
    assert compile_result["success"] is True

    rewritten = _rewrite_as_cte_select(compile_result["segments"])

    upper = rewritten.upper()
    assert rewritten.strip().upper().startswith("WITH ")
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper
    assert "SELECT" in upper


# ─── Parametrized phenotype coverage ────────────────────────────────────


@pytest.mark.parametrize("phenotype_id", [10, 11, 100, 288])
def test_phenotype_resolve_compile_rewrite(phenotype_id):
    """Multiple phenotype IDs resolve, compile, and rewrite successfully."""
    resolved_json = _resolve_cohort_json(phenotype_id=phenotype_id)
    result = compile_cohort(resolved_json, dialect="duckdb")

    assert result["success"] is True, (
        f"Phenotype {phenotype_id} failed to compile: "
        f"{result.get('error', result.get('validation', ''))}"
    )

    rewritten = _rewrite_as_cte_select(result["segments"])
    upper = rewritten.upper()
    assert rewritten.strip().upper().startswith("WITH "), (
        f"Phenotype {phenotype_id}: CTE rewrite does not start with WITH"
    )
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper
