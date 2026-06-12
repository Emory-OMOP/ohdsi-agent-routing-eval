"""
Tests for the CIRCE cohort compiler.

Validates JSON parsing, SQL generation, validation, and MCP tool functions.
"""

import json
from pathlib import Path

import pytest

from circe_compiler.models.cohort_expression import CohortExpression
from circe_compiler.compiler.sql_builder import CohortCompiler
from circe_compiler.validation.validator import CohortValidator, Severity
from circe_compiler.mcp.server import (
    compile_cohort,
    validate_cohort,
    analyze_complexity,
    dry_run,
    _rewrite_as_cte_select,
    _resolve_cohort_json,
    _get_phenotype_dir,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / name) as f:
        return json.load(f)


# ─── Model parsing tests ────────────────────────────────────────────────────


def test_parse_t2dm_cohort():
    """Test that the T2DM example cohort JSON parses correctly."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    expr = CohortExpression.model_validate(data)

    assert expr.cdmVersionRange == ">=5.0.0"
    assert len(expr.ConceptSets) == 3
    assert expr.ConceptSets[0].name == "Type 2 Diabetes Mellitus"
    assert expr.ConceptSets[0].id == 0
    assert expr.ConceptSets[0].expression.items[0].concept.CONCEPT_ID == 201826
    assert expr.ConceptSets[0].expression.items[0].includeDescendants is True

    assert len(expr.PrimaryCriteria.CriteriaList) == 1
    domain, crit = expr.PrimaryCriteria.CriteriaList[0].get_active()
    assert domain == "ConditionOccurrence"
    assert crit.CodesetId == 0

    assert expr.PrimaryCriteria.ObservationWindow.PriorDays == 365
    assert expr.PrimaryCriteria.PrimaryCriteriaLimit.Type == "First"

    assert len(expr.InclusionRules) == 2
    assert expr.InclusionRules[0].name == "Has prior metformin exposure"
    assert expr.InclusionRules[1].name == "No prior heart failure"

    assert expr.EndStrategy is not None
    assert expr.EndStrategy.DateOffset is not None
    assert expr.EndStrategy.DateOffset.Offset == 365


# ─── Compiler tests ─────────────────────────────────────────────────────────


def test_compile_t2dm_postgres():
    """Test SQL generation for the T2DM cohort targeting PostgreSQL."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    expr = CohortExpression.model_validate(data)

    compiler = CohortCompiler(
        cdm_schema="cdm",
        results_schema="results",
        cohort_definition_id=42,
    )
    result = compiler.compile(expr, dialect="postgres")

    assert result.dialect == "postgres"
    assert len(result.segments) > 0
    assert result.sql  # Non-empty SQL

    # Check that key SQL elements are present
    sql = result.sql.lower()
    assert "codesets" in sql  # Concept set temp table
    assert "primary_events" in sql  # Primary events
    assert "condition_occurrence" in sql  # T2DM domain table
    assert "drug_exposure" in sql  # Metformin inclusion rule
    assert "insert into" in sql  # Final cohort insert
    assert "365" in result.sql  # Observation window or end offset

    # Check complexity
    assert result.complexity.concept_set_count == 3
    assert result.complexity.inclusion_rule_count == 2
    assert "condition_occurrence" in result.complexity.tables_scanned
    assert "drug_exposure" in result.complexity.tables_scanned

    # Check template trace
    assert len(result.template_trace) > 0
    domains_activated = [t.domain for t in result.template_trace]
    assert "codeset_insert" in domains_activated
    assert "ConditionOccurrence" in domains_activated


def test_compile_multiple_dialects():
    """Test that compilation works for multiple target dialects."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    expr = CohortExpression.model_validate(data)

    compiler = CohortCompiler()
    for dialect in ["postgres", "duckdb", "tsql", "redshift", "snowflake"]:
        result = compiler.compile(expr, dialect=dialect)
        assert result.sql, f"Empty SQL for dialect {dialect}"
        assert result.dialect == dialect


# ─── Validation tests ───────────────────────────────────────────────────────


def test_validate_valid_cohort():
    """Test that a valid cohort passes validation."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    result = validate_cohort(data)

    assert result["is_valid"] is True
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert len(errors) == 0


def test_validate_invalid_codeset_ref():
    """Test that referencing a non-existent CodesetId is caught."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    # Break it: reference CodesetId 99 which doesn't exist
    data["PrimaryCriteria"]["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] = 99

    result = validate_cohort(data)
    assert result["is_valid"] is False

    error_codes = [i["code"] for i in result["issues"] if i["severity"] == "error"]
    assert "INVALID_CODESET_REF" in error_codes


def test_validate_empty_concept_set():
    """Test that an empty concept set triggers a warning."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    # Add an empty concept set
    data["ConceptSets"].append({
        "id": 99,
        "name": "Empty Set",
        "expression": {"items": []},
    })

    result = validate_cohort(data)
    warning_codes = [i["code"] for i in result["issues"] if i["severity"] == "warning"]
    assert "EMPTY_CONCEPT_SET" in warning_codes


# ─── Complexity analysis tests ───────────────────────────────────────────────


def test_analyze_complexity():
    """Test complexity analysis."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    result = analyze_complexity(data)

    assert result["concept_set_count"] == 3
    assert result["total_concepts"] == 3
    assert result["descendant_expansions"] == 3
    assert result["inclusion_rule_count"] == 2
    assert result["estimated_difficulty"] in ["simple", "moderate", "complex", "very_complex"]
    assert len(result["recommendations"]) > 0


# ─── Dry run tests ───────────────────────────────────────────────────────────


def test_dry_run():
    """Test dry run preview."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    result = dry_run(data)

    assert result["is_valid"] is True
    assert len(result["concept_sets"]) == 3
    assert result["concept_sets"][0]["name"] == "Type 2 Diabetes Mellitus"
    assert result["concept_sets"][0]["has_descendants"] is True
    assert len(result["inclusion_rules"]) == 2
    assert result["inclusion_rules"][0]["name"] == "Has prior metformin exposure"
    assert len(result["tables_scanned"]) > 0
    assert result["sql_preview"]  # Non-empty
    assert result["end_strategy"] == "StartDate + 365 days"


# ─── MCP tool tests ─────────────────────────────────────────────────────────


def test_era_collapsing_phenotype_100():
    """Test era collapsing with Alzheimer's phenotype (EraPad=1)."""
    data = load_fixture("alzheimers_era_collapse.json")
    expr = CohortExpression.model_validate(data)

    compiler = CohortCompiler(
        cdm_schema="cdm",
        results_schema="results",
        cohort_definition_id=100,
    )
    result = compiler.compile(expr, dialect="postgres")

    sql = result.sql.lower()

    # Era collapsing CTEs are present
    assert "cohort_events" in sql
    assert "era_ordered" in sql
    assert "era_groups" in sql
    assert "collapsed_eras" in sql

    # Boundary detection logic
    assert "is_new_era" in sql

    # EraPad value (+ 1) in the LAG comparison
    assert "+ 1" in result.sql

    # Final cohort insert still present
    assert "insert into" in sql

    # QualifiedLimit="First" means ROW_NUMBER is applied on collapsed eras
    assert "row_number" in sql

    # Domain table is referenced
    assert "condition_occurrence" in sql


def test_compile_cohort_mcp_tool():
    """Test the compile_cohort function (as called by MCP)."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    result = compile_cohort(
        json.dumps(data),
        dialect="postgres",
        cdm_schema="my_cdm",
        results_schema="my_results",
    )

    assert result["success"] is True
    assert "my_cdm" in result["sql"]
    assert "my_results" in result["sql"]
    assert result["dialect"] == "postgres"


# ─── CTE rewrite tests ──────────────────────────────────────────────────


def test_rewrite_as_cte_select_t2dm():
    """Test that CTE rewrite produces valid WITH ... SELECT (no temp tables, no INSERT)."""
    data = load_fixture("t2dm_metformin_no_hf.json")
    result = compile_cohort(data, dialect="duckdb")
    assert result["success"] is True

    rewritten = _rewrite_as_cte_select(result["segments"])

    # Must start with WITH
    assert rewritten.strip().upper().startswith("WITH ")

    # Must not contain CREATE TEMP TABLE or INSERT INTO
    upper = rewritten.upper()
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper

    # Must contain SELECT (the final query)
    assert "SELECT" in upper

    # Must reference the CTE names from compilation
    assert "codesets" in rewritten.lower()
    assert "primary_events" in rewritten.lower()


def test_rewrite_as_cte_select_era_collapse():
    """Test CTE rewrite with era collapsing (Alzheimer's phenotype)."""
    data = load_fixture("alzheimers_era_collapse.json")
    result = compile_cohort(data, dialect="duckdb")
    assert result["success"] is True

    rewritten = _rewrite_as_cte_select(result["segments"])

    upper = rewritten.upper()
    assert rewritten.strip().upper().startswith("WITH ")
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper

    # Era collapsing CTEs should be hoisted into the top-level WITH
    lower = rewritten.lower()
    assert "cohort_events" in lower
    assert "collapsed_eras" in lower


# ─── Phenotype resolution tests ──────────────────────────────────────────


def test_resolve_phenotype_id_288():
    """Phenotype ID 288 loads valid JSON from disk."""
    result = _resolve_cohort_json(phenotype_id=288)
    data = json.loads(result)
    assert "PrimaryCriteria" in data
    assert "ConceptSets" in data


def test_resolve_direct_json_passthrough():
    """Direct JSON string passes through unchanged."""
    fixture = load_fixture("t2dm_metformin_no_hf.json")
    raw = json.dumps(fixture)
    result = _resolve_cohort_json(cohort_json=raw)
    assert result == raw


def test_resolve_both_provided_raises():
    """Providing both cohort_json and phenotype_id raises ValueError."""
    with pytest.raises(ValueError, match="not both"):
        _resolve_cohort_json(cohort_json='{"foo": 1}', phenotype_id=288)


def test_resolve_neither_provided_raises():
    """Providing neither cohort_json nor phenotype_id raises ValueError."""
    with pytest.raises(ValueError, match="Provide either"):
        _resolve_cohort_json()


def test_resolve_invalid_phenotype_id_raises():
    """Invalid phenotype ID 999999 raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        _resolve_cohort_json(phenotype_id=999999)


def test_resolve_phenotype_10_compiles():
    """Phenotype 10 resolves and compiles successfully."""
    resolved = _resolve_cohort_json(phenotype_id=10)
    result = compile_cohort(resolved, dialect="duckdb")
    assert result["success"] is True
    assert result["sql"]


def test_resolve_phenotype_dir_env_override(monkeypatch, tmp_path):
    """PHENOTYPE_LIBRARY_DIR env var overrides default path."""
    # Create a fake phenotype file
    cohort_file = tmp_path / "42.json"
    fixture = load_fixture("t2dm_metformin_no_hf.json")
    cohort_file.write_text(json.dumps(fixture))

    monkeypatch.setenv("PHENOTYPE_LIBRARY_DIR", str(tmp_path))

    result = _resolve_cohort_json(phenotype_id=42)
    data = json.loads(result)
    assert data["PrimaryCriteria"] is not None

    # Verify _get_phenotype_dir uses the env var
    assert _get_phenotype_dir() == tmp_path
