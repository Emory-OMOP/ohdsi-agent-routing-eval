"""
MCP Server for OHDSI CIRCE Cohort Compiler.

Exposes deterministic cohort compilation as MCP tools, complementing
FastOMOP/OMCP's LLM-generated SQL approach. Tools:

  - compile_cohort: JSON → optimized SQL (deterministic, auditable)
  - validate_cohort: Semantic validation of cohort definitions
  - analyze_complexity: Static analysis and performance prediction
  - transpile_sql: Convert SQL between database dialects
  - dry_run: Estimate what a cohort definition would do without executing

Compatible with Claude Desktop, LibreChat, and any MCP client.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from circe_compiler.builder.cohort_builder import (
    build_cohort_definition_from_spec,
    CohortDefinitionSpec,
)
from circe_compiler.compiler.sql_builder import CohortCompiler
from circe_compiler.mcp.db import get_rw_connection, next_cohort_definition_id
from circe_compiler.models.cohort_expression import CohortExpression
from circe_compiler.validation.validator import CohortValidator

logger = logging.getLogger(__name__)

_MAX_SQL_PREVIEW = 800


# ─── Phenotype resolution ────────────────────────────────────────────────────


def _get_phenotype_dir() -> Path:
    """Return the directory containing phenotype library cohort JSON files.

    Checks PHENOTYPE_LIBRARY_DIR env var first, then falls back to the
    repo-relative path: mcp_server/data/phenotype_library/cohorts/
    """
    env_dir = os.environ.get("PHENOTYPE_LIBRARY_DIR")
    if env_dir:
        return Path(env_dir)
    # server.py is at servers/circe-compiler/src/circe_compiler/mcp/server.py
    # parents[5] is the repo root (set PHENOTYPE_LIBRARY_DIR to avoid relying on this).
    repo_root = Path(__file__).resolve().parents[5]
    return repo_root / "servers" / "ohdsi-vocab" / "data" / "phenotype_library" / "cohorts"


def _resolve_cohort_json(
    cohort_json: str = "",
    phenotype_id: int | None = None,
) -> str:
    """Resolve a cohort definition from either direct JSON or a phenotype ID.

    Exactly one of cohort_json or phenotype_id must be provided.
    When phenotype_id is given, loads the JSON from disk.

    Returns:
        The cohort definition as a JSON string.

    Raises:
        ValueError: If both, neither, or an invalid phenotype_id is provided.
    """
    has_json = bool(cohort_json and cohort_json.strip())
    has_id = phenotype_id is not None

    if has_json and has_id:
        raise ValueError(
            "Provide either cohort_json or phenotype_id, not both."
        )
    if not has_json and not has_id:
        raise ValueError(
            "Provide either cohort_json (raw CIRCE JSON) or phenotype_id "
            "(integer from the OHDSI Phenotype Library)."
        )

    if has_id:
        phenotype_dir = _get_phenotype_dir()
        path = phenotype_dir / f"{phenotype_id}.json"
        if not path.exists():
            raise ValueError(
                f"Phenotype ID {phenotype_id} not found at {path}. "
                f"Use get_phenotype_list to browse available phenotypes."
            )
        return path.read_text()

    return cohort_json


# ─── Tool implementations ───────────────────────────────────────────────────


def compile_cohort(
    cohort_json: str | dict,
    dialect: str = "postgres",
    cdm_schema: str = "main_cdm",
    vocab_schema: str = "main_vocab",
    results_schema: str = "results",
    cohort_definition_id: int = 1,
    target_table: str = "cohort",
) -> dict[str, Any]:
    """
    Compile an OHDSI CIRCE cohort definition JSON to SQL.

    Args:
        cohort_json: The cohort definition as JSON string or dict.
        dialect: Target SQL dialect (postgres, duckdb, tsql, redshift, snowflake, bigquery).
        cdm_schema: Schema containing OMOP CDM tables.
        vocab_schema: Schema containing vocabulary tables (concept_ancestor, etc).
        results_schema: Schema for the output cohort table.
        cohort_definition_id: ID to assign in the cohort table.
        target_table: Name of the cohort table.

    Returns:
        Dict with sql, segments, complexity, warnings, and optimization_log.
    """
    if isinstance(cohort_json, str):
        cohort_dict = json.loads(cohort_json)
    else:
        cohort_dict = cohort_json

    # Parse into model
    expression = CohortExpression.model_validate(cohort_dict)

    # Validate first
    validator = CohortValidator()
    validation = validator.validate(expression)

    if not validation.is_valid:
        return {
            "success": False,
            "error": "Validation failed",
            "validation": {
                "is_valid": False,
                "summary": validation.summary,
                "issues": [
                    {
                        "severity": issue.severity.value,
                        "code": issue.code,
                        "message": issue.message,
                        "path": issue.path,
                    }
                    for issue in validation.issues
                ],
            },
        }

    # Compile
    compiler = CohortCompiler(
        cdm_schema=cdm_schema,
        vocab_schema=vocab_schema,
        results_schema=results_schema,
        cohort_definition_id=cohort_definition_id,
        target_table=target_table,
    )
    result = compiler.compile(expression, dialect=dialect)

    return {
        "success": True,
        "sql": result.sql,
        "dialect": result.dialect,
        "segments": result.segments,
        "complexity": {
            "concept_set_count": result.complexity.concept_set_count,
            "total_concepts": result.complexity.total_concepts,
            "descendant_expansions": result.complexity.descendant_expansions,
            "inclusion_rule_count": result.complexity.inclusion_rule_count,
            "correlated_criteria_count": result.complexity.correlated_criteria_count,
            "tables_scanned": result.complexity.tables_scanned,
            "risk_factors": result.complexity.risk_factors,
        },
        "template_trace": [
            {
                "domain": t.domain,
                "reason": t.reason,
                "codeset_id": t.codeset_id,
                "concept_count": t.concept_count,
            }
            for t in result.template_trace
        ],
        "warnings": result.warnings,
        "optimization_log": result.optimization_log,
        "validation": {
            "is_valid": True,
            "summary": validation.summary,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                    "path": issue.path,
                }
                for issue in validation.issues
            ],
        },
    }


def validate_cohort(cohort_json: str | dict) -> dict[str, Any]:
    """
    Validate an OHDSI CIRCE cohort definition without compiling it.

    Returns validation issues including semantic errors that CIRCE silently ignores.
    """
    if isinstance(cohort_json, str):
        cohort_dict = json.loads(cohort_json)
    else:
        cohort_dict = cohort_json

    try:
        expression = CohortExpression.model_validate(cohort_dict)
    except Exception as e:
        return {
            "is_valid": False,
            "parse_error": str(e),
            "summary": "Failed to parse JSON as CohortExpression",
            "issues": [
                {
                    "severity": "error",
                    "code": "PARSE_ERROR",
                    "message": str(e),
                    "path": "",
                }
            ],
        }

    validator = CohortValidator()
    result = validator.validate(expression)

    return {
        "is_valid": result.is_valid,
        "summary": result.summary,
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
                "path": issue.path,
            }
            for issue in result.issues
        ],
    }


def analyze_complexity(cohort_json: str | dict) -> dict[str, Any]:
    """
    Static analysis of a cohort definition's complexity.

    Predicts performance characteristics without executing the query.
    """
    if isinstance(cohort_json, str):
        cohort_dict = json.loads(cohort_json)
    else:
        cohort_dict = cohort_json

    expression = CohortExpression.model_validate(cohort_dict)

    compiler = CohortCompiler()
    # We compile to get the complexity analysis but don't return SQL
    result = compiler.compile(expression, dialect="postgres")

    c = result.complexity
    return {
        "concept_set_count": c.concept_set_count,
        "total_concepts": c.total_concepts,
        "descendant_expansions": c.descendant_expansions,
        "inclusion_rule_count": c.inclusion_rule_count,
        "correlated_criteria_count": c.correlated_criteria_count,
        "tables_scanned": c.tables_scanned,
        "risk_factors": c.risk_factors,
        "estimated_difficulty": _classify_difficulty(c),
        "recommendations": _generate_recommendations(c, expression),
    }


def transpile_sql(
    sql: str,
    from_dialect: str = "postgres",
    to_dialect: str = "duckdb",
) -> dict[str, Any]:
    """
    Transpile SQL between database dialects using SQLGlot.

    Replaces OHDSI's SqlRender/SqlTranslate chain.
    """
    import sqlglot

    try:
        result = sqlglot.transpile(sql, read=from_dialect, write=to_dialect)
        return {
            "success": True,
            "sql": result[0] if result else "",
            "from_dialect": from_dialect,
            "to_dialect": to_dialect,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "from_dialect": from_dialect,
            "to_dialect": to_dialect,
        }


def dry_run(
    cohort_json: str | dict,
    dialect: str = "postgres",
) -> dict[str, Any]:
    """
    Estimate what a cohort definition would do without executing it.

    Returns: concept sets expanded, tables that would be scanned,
    estimated query complexity, and the SQL that would be generated.
    """
    if isinstance(cohort_json, str):
        cohort_dict = json.loads(cohort_json)
    else:
        cohort_dict = cohort_json

    expression = CohortExpression.model_validate(cohort_dict)

    # Validation
    validator = CohortValidator()
    validation = validator.validate(expression)

    # Compilation
    compiler = CohortCompiler()
    result = compiler.compile(expression, dialect=dialect)

    # Build concept set summary
    concept_sets_summary = []
    for cs in expression.ConceptSets:
        items = cs.expression.items if cs.expression else []
        concept_sets_summary.append({
            "id": cs.id,
            "name": cs.name,
            "source_concepts": len(items),
            "has_descendants": any(i.includeDescendants for i in items),
            "has_exclusions": any(i.isExcluded for i in items),
            "has_mapped": any(i.includeMapped for i in items),
        })

    # Build inclusion rules summary
    inclusion_rules_summary = []
    for i, rule in enumerate(expression.InclusionRules):
        inclusion_rules_summary.append({
            "index": i,
            "name": rule.name,
            "criteria_count": len(rule.expression.CriteriaList),
            "group_type": rule.expression.Type,
        })

    return {
        "is_valid": validation.is_valid,
        "validation_summary": validation.summary,
        "concept_sets": concept_sets_summary,
        "inclusion_rules": inclusion_rules_summary,
        "tables_scanned": result.complexity.tables_scanned,
        "complexity": {
            "total_concepts": result.complexity.total_concepts,
            "descendant_expansions": result.complexity.descendant_expansions,
            "risk_factors": result.complexity.risk_factors,
            "estimated_difficulty": _classify_difficulty(result.complexity),
        },
        "sql": result.sql,
        "sql_segment_count": len(result.segments),
        "end_strategy": _describe_end_strategy(expression),
        "collapse_settings": {
            "type": expression.CollapseSettings.CollapseType,
            "era_pad": expression.CollapseSettings.EraPad,
        },
    }


def build_cohort(spec_json: str | dict) -> dict[str, Any]:
    """
    Build a CIRCE cohort definition JSON from a simplified spec.

    Accepts a simplified JSON spec with concept_sets, primary_criteria,
    inclusion_rules, and exclusion_criteria. Returns valid CIRCE JSON
    ready for compile_cohort_definition.

    Args:
        spec_json: Builder spec as JSON string or dict.

    Returns:
        Dict with success, cohort_json, validation, concept_set_mapping, summary.
    """
    return build_cohort_definition_from_spec(spec_json)


# ─── Helper functions ────────────────────────────────────────────────────────


def _classify_difficulty(complexity) -> str:
    """Classify overall query difficulty."""
    score = 0
    score += complexity.concept_set_count
    score += complexity.total_concepts // 100
    score += complexity.descendant_expansions * 2
    score += complexity.inclusion_rule_count * 3
    score += complexity.correlated_criteria_count * 5
    score += len(complexity.tables_scanned) * 2
    score += len(complexity.risk_factors) * 10

    if score < 10:
        return "simple"
    elif score < 30:
        return "moderate"
    elif score < 60:
        return "complex"
    else:
        return "very_complex"


def _generate_recommendations(complexity, expression: CohortExpression) -> list[str]:
    """Generate actionable recommendations based on complexity analysis."""
    recs = []

    if complexity.total_concepts > 5000:
        recs.append(
            "Consider materializing concept sets as a permanent table "
            "rather than temp table to avoid repeated expansion"
        )

    if complexity.descendant_expansions > 20:
        recs.append(
            "Many descendant expansions detected. Consider pre-computing "
            "concept_ancestor joins in a materialized view"
        )

    if complexity.correlated_criteria_count > 3:
        recs.append(
            "Multiple correlated subqueries may cause slow performance. "
            "Consider breaking into sequential temp table operations"
        )

    if "condition_occurrence" in complexity.tables_scanned and "drug_exposure" in complexity.tables_scanned:
        recs.append(
            "Both condition_occurrence and drug_exposure scanned. "
            "Ensure date range filters are pushed down to avoid full table scans"
        )

    obs = expression.PrimaryCriteria.ObservationWindow
    if obs.PriorDays == 0 and obs.PostDays == 0:
        recs.append(
            "No observation window constraints. This may include patients "
            "with very short observation periods"
        )

    if not recs:
        recs.append("No performance concerns detected")

    return recs


def _describe_end_strategy(expression: CohortExpression) -> str:
    """Human-readable description of the end strategy."""
    if expression.EndStrategy is None:
        return "End of continuous observation"

    if expression.EndStrategy.DateOffset:
        off = expression.EndStrategy.DateOffset
        if off.Offset == 0:
            return f"Same as {off.DateField}"
        return f"{off.DateField} + {off.Offset} days"

    if expression.EndStrategy.CustomEra:
        era = expression.EndStrategy.CustomEra
        return (
            f"End of continuous drug era (CodesetId={era.DrugCodesetId}, "
            f"gap={era.GapDays} days, offset={era.Offset} days)"
        )

    return "End of continuous observation"


# ─── CTE rewrite + OMCP proxy ────────────────────────────────────────────


_SEGMENT_COMMENT_RE = re.compile(r"^-- \[CIRCE:segment=[^\]]*\]\n?", re.MULTILINE)
_CREATE_TEMP_RE = re.compile(
    r"CREATE TEMP TABLE\s+(\w+)\s+AS\n",
    re.IGNORECASE,
)
_INSERT_INTO_RE = re.compile(
    r"INSERT INTO\s+\S+\n",
    re.IGNORECASE,
)


def _rewrite_as_cte_select(segments: list[str]) -> str:
    """Post-process compiled SQL segments into a single CTE-based SELECT.

    Transforms CREATE TEMP TABLE / INSERT INTO patterns into a single
    WITH ... SELECT statement that can be executed as a read-only query.
    Handles inner WITH CTEs (era collapsing) by hoisting them into the
    top-level CTE chain.
    """
    ctes: list[str] = []
    final_sql = ""

    for i, segment in enumerate(segments):
        # Strip CIRCE segment comments
        cleaned = _SEGMENT_COMMENT_RE.sub("", segment).strip()

        is_final = i == len(segments) - 1

        if is_final:
            # Final segment: may have WITH ... INSERT INTO ... SELECT ...
            # Strip INSERT INTO line, keep SELECT; hoist inner WITH CTEs
            cleaned = _INSERT_INTO_RE.sub("", cleaned).strip()

            if cleaned.upper().startswith("WITH "):
                # Extract inner CTEs and final SELECT
                inner_ctes, final_select = _split_with_clause(cleaned)
                ctes.extend(inner_ctes)
                final_sql = final_select
            else:
                final_sql = cleaned
        else:
            # Non-final segment: CREATE TEMP TABLE <name> AS <body>
            m = _CREATE_TEMP_RE.match(cleaned)
            if m:
                table_name = m.group(1)
                body = cleaned[m.end():]
                ctes.append(f"{table_name} AS (\n{body}\n)")
            else:
                # Shouldn't happen, but pass through as-is
                ctes.append(cleaned)

    if ctes:
        cte_block = "WITH " + ",\n".join(ctes) + "\n"
        return cte_block + final_sql
    else:
        return final_sql


def _split_with_clause(sql: str) -> tuple[list[str], str]:
    """Split a WITH ... SELECT into (list of CTE strings, final SELECT).

    Handles nested parentheses to correctly find CTE boundaries.
    """
    # Remove leading WITH keyword
    body = sql[4:].strip()  # strip "WITH"

    ctes: list[str] = []
    pos = 0

    while pos < len(body):
        # Find CTE name — everything before "AS ("
        as_match = re.search(r"(\w+)\s+AS\s*\(", body[pos:], re.IGNORECASE)
        if not as_match:
            break

        cte_name = as_match.group(1)
        # Position of opening paren
        paren_start = pos + as_match.end() - 1  # index of '('
        # Find matching closing paren
        depth = 1
        idx = paren_start + 1
        while idx < len(body) and depth > 0:
            if body[idx] == "(":
                depth += 1
            elif body[idx] == ")":
                depth -= 1
            idx += 1

        cte_body = body[paren_start + 1 : idx - 1]
        ctes.append(f"{cte_name} AS (\n{cte_body}\n)")

        # Move past the closing paren and any comma
        pos = idx
        remaining = body[pos:].lstrip()
        if remaining.startswith(","):
            pos = pos + (len(body[pos:]) - len(remaining)) + 1
        else:
            pos = pos + (len(body[pos:]) - len(remaining))

    # Whatever remains is the final SELECT
    final_select = body[pos:].strip()
    return ctes, final_select


async def _execute_via_omcp(sql: str, omcp_url: str) -> dict[str, Any]:
    """Proxy a SELECT query to OMCP's Select_Query tool via fastmcp.Client."""
    try:
        from fastmcp import Client
    except ImportError:
        return {
            "error": "fastmcp not installed — cannot proxy to OMCP",
            "omcp_url": omcp_url,
        }

    try:
        async with Client(omcp_url) as client:
            result = await client.call_tool("Select_Query", {"query": sql})
            # Extract text from MCP result
            if hasattr(result, "content"):
                content = result.content
            else:
                content = result

            if isinstance(content, list):
                parts = []
                for item in content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                    elif isinstance(item, dict) and "text" in item:
                        parts.append(item["text"])
                    else:
                        parts.append(str(item))
                text = "\n".join(parts)
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)

            # Try to parse as JSON
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"result": text}
    except Exception as e:
        return {
            "error": f"OMCP execution failed: {e}",
            "omcp_url": omcp_url,
        }


# ─── Cohort materialization ─────────────────────────────────────────────────


def _materialize_cohort(
    segments: list[str],
    results_schema: str = "results",
    cohort_definition_id: int = 1,
    cohort_name: str | None = None,
    source_identifier: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Persist compiled cohort SQL to results.cohort, return summary stats.

    Matches the ATLAS workflow: execute the CIRCE-compiled segments
    (CREATE TEMP TABLE ... / INSERT INTO ...) directly against DuckDB,
    then return a summary instead of raw patient rows.

    Args:
        segments: Compiled SQL segments from CohortCompiler.
        results_schema: Schema containing the cohort table.
        cohort_definition_id: ID to assign in the cohort table.
        cohort_name: Human-readable cohort name for metadata.
        source_identifier: Source identifier (e.g. phenotype_id or spec hash).
        db_path: Override DuckDB path (for testing).

    Returns:
        Summary dict with cohort_definition_id, status, subject_count, etc.
    """
    try:
        with get_rw_connection(db_path=db_path) as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                # Clear any previous run with this ID
                conn.execute(
                    f"DELETE FROM {results_schema}.cohort "
                    f"WHERE cohort_definition_id = ?",
                    [cohort_definition_id],
                )

                # Execute each segment sequentially
                for segment in segments:
                    cleaned = _SEGMENT_COMMENT_RE.sub("", segment).strip()
                    if cleaned:
                        conn.execute(cleaned)

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            # Gather summary stats
            row = conn.execute(
                f"SELECT COUNT(DISTINCT subject_id) AS subject_count, "
                f"COUNT(*) AS row_count, "
                f"MIN(cohort_start_date) AS min_start, "
                f"MAX(cohort_start_date) AS max_start, "
                f"MIN(cohort_end_date) AS min_end, "
                f"MAX(cohort_end_date) AS max_end "
                f"FROM {results_schema}.cohort "
                f"WHERE cohort_definition_id = ?",
                [cohort_definition_id],
            ).fetchone()

            subject_count = row[0] if row else 0
            row_count = row[1] if row else 0
            min_start = str(row[2]) if row and row[2] else None
            max_start = str(row[3]) if row and row[3] else None
            min_end = str(row[4]) if row and row[4] else None
            max_end = str(row[5]) if row and row[5] else None

            # Upsert cohort_generation metadata
            try:
                conn.execute(
                    f"DELETE FROM {results_schema}.cohort_generation "
                    f"WHERE cohort_definition_id = ?",
                    [cohort_definition_id],
                )
                conn.execute(
                    f"INSERT INTO {results_schema}.cohort_generation "
                    f"(cohort_definition_id, cohort_name, source_type, "
                    f"source_identifier, generated_at, subject_count, status) "
                    f"VALUES (?, ?, 'circe-compiler', ?, NOW(), ?, 'COMPLETE')",
                    [
                        cohort_definition_id,
                        cohort_name or f"Cohort {cohort_definition_id}",
                        source_identifier or "",
                        subject_count,
                    ],
                )
            except Exception as e:
                # cohort_generation is optional metadata — don't fail the whole op
                logger.warning("Failed to upsert cohort_generation: %s", e)

            summary = {
                "cohort_definition_id": cohort_definition_id,
                "status": "COMPLETE",
                "subject_count": subject_count,
                "row_count": row_count,
            }
            if min_start and max_start:
                summary["cohort_start_date_range"] = [min_start, max_start]
            if min_end and max_end:
                summary["cohort_end_date_range"] = [min_end, max_end]

            return summary

    except FileNotFoundError as e:
        return {"error": str(e), "status": "FAILED"}
    except Exception as e:
        return {"error": f"Materialization failed: {e}", "status": "FAILED"}


# ─── MCP Server setup ───────────────────────────────────────────────────────

def create_mcp_server():
    """
    Create and return an MCP server instance with all tools registered.

    Usage with FastMCP:
        server = create_mcp_server()
        server.run(transport="stdio")
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.warning("mcp package not installed; MCP server unavailable")
        return None

    mcp = FastMCP(
        "circe-compiler",
        instructions=(
            "Deterministic OHDSI CIRCE cohort definition compiler. "
            "Compiles cohort definition JSON (the OHDSI standard format "
            "from ATLAS and Phenotype Library) to executable SQL via SQLGlot.\n\n"
            "Same input always produces same output — suitable for regulatory "
            "documentation and reproducible research. Supports 8 SQL dialects: "
            "postgres, duckdb, tsql, redshift, snowflake, bigquery, spark, trino.\n\n"
            "Schema configuration: The connected DuckDB database uses separate schemas "
            "for vocabulary and clinical tables. When compiling for this database, use "
            "dialect='duckdb', cdm_schema='main_cdm', vocab_schema='main_vocab'. "
            "These are the defaults, so you can omit them unless targeting a different database.\n\n"
            "TWO ONE-CALL PATHS (use these — never relay JSON between tools):\n\n"
            "Path A — Existing phenotype: compile_cohort_definition(phenotype_id=288, execute=True)\n"
            "  Loads definition from Phenotype Library by ID, compiles to SQL, persists cohort "
            "to results.cohort, and returns summary stats (subject count, date ranges, "
            "cohort_definition_id). No need to call get_phenotype first.\n\n"
            "Path B — Novel cohort: build_cohort_definition(spec_json=..., execute=True)\n"
            "  Builds CIRCE JSON from spec, compiles to SQL, persists cohort to results.cohort, "
            "and returns summary stats. No need to call compile_cohort_definition separately.\n\n"
            "To query individual patients from a generated cohort, use Select_Query on "
            "results.cohort WHERE cohort_definition_id = <id>.\n\n"
            "CRITICAL: Never copy JSON output from one tool into another tool's input. "
            "Use phenotype_id to reference existing definitions. Use build_cohort_definition "
            "with execute=True to build and run novel definitions in one call.\n\n"
            "Workflow: (1) Use vocabulary tools (search_concepts, get_concept_descendants) "
            "to find concept_ids. (2) Choose Path A or Path B above. "
            "(3) Always use execute=True for cohort queries."
        ),
    )

    @mcp.tool()
    def compile_cohort_definition(
        cohort_json: str = "",
        phenotype_id: int | None = None,
        dialect: str = "duckdb",
        cdm_schema: str = "main_cdm",
        vocab_schema: str = "main_vocab",
        results_schema: str = "results",
        execute: bool = False,
        return_mode: str = "summary",
    ) -> str:
        """
        Compile an OHDSI CIRCE cohort definition JSON to SQL, optionally executing it.

        This is the deterministic compilation path: same input always produces
        same output, suitable for regulatory documentation and reproducible
        research. Unlike LLM-generated SQL, this produces auditable,
        standards-compliant cohort queries from a formal definition.

        Provide EITHER cohort_json (raw CIRCE JSON string) OR phenotype_id
        (integer ID from the OHDSI Phenotype Library). When phenotype_id is
        given, the definition is loaded directly from disk — no need to call
        get_phenotype first.

        When execute=True (recommended for cohort queries), the compiled SQL
        is persisted to results.cohort and returns summary stats (subject count,
        date ranges, cohort_definition_id) — not individual patient rows.
        To query individual patients, use Select_Query on results.cohort
        WHERE cohort_definition_id = <returned_id>.

        When execute=False, returns compilation metadata and a capped SQL
        preview (return_mode="summary", the default). Use return_mode="full"
        only for debugging when you need the complete SQL and segment details.

        Args:
            cohort_json: OHDSI cohort definition JSON string (from ATLAS export or build_cohort_definition)
            phenotype_id: Integer ID from the OHDSI Phenotype Library (e.g. 288). Loads JSON from disk.
            dialect: Target SQL dialect. Use 'duckdb' for the local Synthea database.
            cdm_schema: Schema with OMOP CDM clinical tables (person, condition_occurrence, etc). Default 'main_cdm'.
            vocab_schema: Schema with vocabulary tables (concept, concept_ancestor, concept_relationship). Default 'main_vocab'.
            results_schema: Schema for the output cohort table (only needed for full INSERT pipeline).
            execute: If True, persist cohort to results.cohort and return summary stats. Recommended for cohort queries.
            return_mode: "summary" (default, compact) or "full" (debugging only — returns complete SQL and segments)
        """
        resolved_json = _resolve_cohort_json(cohort_json, phenotype_id)

        if not execute:
            result = compile_cohort(
                resolved_json, dialect=dialect,
                cdm_schema=cdm_schema, vocab_schema=vocab_schema,
                results_schema=results_schema,
            )
            if return_mode != "full":
                full_sql = result.pop("sql", "")
                result.pop("segments", None)
                result["sql_preview"] = full_sql[:_MAX_SQL_PREVIEW] + (
                    f"\n-- [truncated — {len(full_sql)} chars total. "
                    "Use execute=True to materialize.]"
                    if len(full_sql) > _MAX_SQL_PREVIEW else ""
                )
            return json.dumps(result, indent=2)

        # execute=True: get next ID before compilation (ID is baked into SQL)
        try:
            with get_rw_connection() as conn:
                cohort_id = next_cohort_definition_id(conn, schema=results_schema)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to allocate cohort ID: {e}",
            }, indent=2)

        result = compile_cohort(
            resolved_json, dialect=dialect,
            cdm_schema=cdm_schema, vocab_schema=vocab_schema,
            results_schema=results_schema,
            cohort_definition_id=cohort_id,
        )

        if not result.get("success"):
            return json.dumps(result, indent=2)

        # Materialize cohort to results.cohort
        source_id = str(phenotype_id) if phenotype_id else "cohort_json"
        mat_result = _materialize_cohort(
            segments=result["segments"],
            results_schema=results_schema,
            cohort_definition_id=cohort_id,
            cohort_name=f"Phenotype {phenotype_id}" if phenotype_id else None,
            source_identifier=source_id,
        )

        # Return compact summary (no segments/sql to avoid flooding context)
        return json.dumps({
            "success": True,
            "materialization": mat_result,
            "complexity": result.get("complexity"),
            "warnings": result.get("warnings"),
            "validation": result.get("validation"),
        }, indent=2)

    @mcp.tool()
    def validate_cohort_definition(
        cohort_json: str = "",
        phenotype_id: int | None = None,
    ) -> str:
        """
        Validate an OHDSI cohort definition for semantic correctness.

        Run this before compile_cohort_definition to catch errors early.
        Checks for: invalid codeset references, empty concept sets,
        impossible temporal logic, extreme observation windows,
        and performance risk factors that OHDSI ATLAS silently ignores.

        Provide EITHER cohort_json OR phenotype_id (not both).

        Args:
            cohort_json: OHDSI cohort definition JSON string
            phenotype_id: Integer ID from the OHDSI Phenotype Library. Loads JSON from disk.
        """
        resolved_json = _resolve_cohort_json(cohort_json, phenotype_id)
        result = validate_cohort(resolved_json)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def analyze_cohort_complexity(
        cohort_json: str = "",
        phenotype_id: int | None = None,
    ) -> str:
        """
        Analyze a cohort definition's complexity and predict performance.

        Returns concept set sizes, table scan estimates, risk factors,
        difficulty classification, and actionable recommendations.

        Provide EITHER cohort_json OR phenotype_id (not both).

        Args:
            cohort_json: OHDSI cohort definition JSON string
            phenotype_id: Integer ID from the OHDSI Phenotype Library. Loads JSON from disk.
        """
        resolved_json = _resolve_cohort_json(cohort_json, phenotype_id)
        result = analyze_complexity(resolved_json)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def transpile_sql_dialect(
        sql: str,
        from_dialect: str = "postgres",
        to_dialect: str = "duckdb",
    ) -> str:
        """
        Transpile SQL between database dialects.

        Replaces OHDSI's SqlRender/SqlTranslate chain with SQLGlot.
        Supports: postgres, duckdb, tsql, redshift, snowflake, bigquery, spark, trino.

        Args:
            sql: The SQL to transpile
            from_dialect: Source SQL dialect
            to_dialect: Target SQL dialect
        """
        result = transpile_sql(sql, from_dialect, to_dialect)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def cohort_dry_run(
        cohort_json: str = "",
        phenotype_id: int | None = None,
        dialect: str = "duckdb",
        return_mode: str = "summary",
    ) -> str:
        """
        Preview what a cohort definition would do without executing it.

        Use this before compile_cohort_definition to understand the scope
        and performance impact. Returns: concept set details, tables
        scanned, complexity analysis, SQL preview, and recommendations.

        This is the recommended first step when working with an unfamiliar
        cohort definition.

        Provide EITHER cohort_json OR phenotype_id (not both).

        Args:
            cohort_json: OHDSI cohort definition JSON string
            phenotype_id: Integer ID from the OHDSI Phenotype Library. Loads JSON from disk.
            dialect: Target SQL dialect for the preview
            return_mode: "summary" (default, compact) or "full" (debugging only — returns complete SQL preview)
        """
        resolved_json = _resolve_cohort_json(cohort_json, phenotype_id)
        result = dry_run(resolved_json, dialect=dialect)
        if return_mode != "full":
            full_sql = result.pop("sql", "")
            result["sql_preview"] = full_sql[:_MAX_SQL_PREVIEW] + (
                f"\n-- [truncated — {len(full_sql)} chars total]"
                if len(full_sql) > _MAX_SQL_PREVIEW else ""
            )
        return json.dumps(result, indent=2)

    @mcp.tool()
    def build_cohort_definition(
        spec_json: str,
        compile: bool = False,
        execute: bool = False,
        dialect: str = "duckdb",
        cdm_schema: str = "main_cdm",
        vocab_schema: str = "main_vocab",
        results_schema: str = "results",
    ) -> str:
        """
        Build a CIRCE cohort definition JSON from a simplified specification.

        Use this tool to construct novel cohort definitions programmatically.
        With compile=True or execute=True, the built definition is compiled
        (and optionally persisted to results.cohort) in a single call — no need
        to call compile_cohort_definition separately.

        When execute=True, persists the cohort to results.cohort and returns
        summary stats (subject count, date ranges, cohort_definition_id) —
        not individual patient rows. To query individual patients, use
        Select_Query on results.cohort WHERE cohort_definition_id = <id>.

        IMPORTANT: Always use vocabulary tools (search_concepts, get_concept)
        first to find correct concept_ids before calling this tool. Never
        guess concept_ids.

        Workflow (one-call):
        1. search_concepts to find concept_ids for your clinical criteria
        2. build_cohort_definition(spec_json=..., execute=True)
           → builds CIRCE JSON, compiles to SQL, persists to results.cohort

        === Example 1: Minimal (condition only) ===
        {
          "concept_sets": [
            {"name": "Type 2 Diabetes", "domain": "Condition",
             "concepts": [{"concept_id": 201826, "include_descendants": true}]}
          ],
          "primary_criteria": {"concept_set": "Type 2 Diabetes", "first_occurrence": true},
          "observation_window": {"days_before": 365, "days_after": 0}
        }

        === Example 2: Exclusion (condition excluding comorbidity) ===
        {
          "concept_sets": [
            {"name": "HTN", "domain": "Condition",
             "concepts": [{"concept_id": 316866, "include_descendants": true}]},
            {"name": "CKD", "domain": "Condition",
             "concepts": [{"concept_id": 46271022, "include_descendants": true}]}
          ],
          "primary_criteria": {"concept_set": "HTN", "first_occurrence": true},
          "observation_window": {"days_before": 365, "days_after": 0},
          "exclusion_criteria": [
            {"name": "No prior CKD", "concept_set": "CKD"}
          ]
        }

        === Example 3: Inclusion + demographics (drug + age filter) ===
        {
          "concept_sets": [
            {"name": "T2DM", "domain": "Condition",
             "concepts": [{"concept_id": 201826, "include_descendants": true}]},
            {"name": "Metformin", "domain": "Drug",
             "concepts": [{"concept_id": 1503297, "include_descendants": true}]}
          ],
          "primary_criteria": {"concept_set": "T2DM", "first_occurrence": true},
          "observation_window": {"days_before": 365, "days_after": 0},
          "inclusion_rules": [
            {"name": "On Metformin", "concept_set": "Metformin",
             "temporal": {"days_before": 365, "days_after": 0},
             "occurrence": {"type": "at_least", "count": 1},
             "demographic": {"age_min": 18, "age_max": 65}}
          ]
        }

        Key spec structures:

        ConceptSetSpec: {"name": str, "domain": str, "concepts": [ConceptSpec]}
          ConceptSpec: {"concept_id": int, "include_descendants": bool}

        PrimaryCriteriaSpec: {"concept_set": "<name>", "first_occurrence": bool}

        ExclusionCriterionSpec: {"name": str, "concept_set": "<name>",
          "temporal": TemporalSpec (optional)}
          → Converted to inclusion rule with exactly 0 occurrences.

        InclusionRuleSpec: {"name": str, "concept_set": "<name>",
          "temporal": {"days_before": int, "days_after": int},
          "occurrence": {"type": "at_least"|"at_most"|"exactly", "count": int},
          "demographic": {"age_min": int, "age_max": int,
                          "gender_concept_ids": [int]}}

        DemographicSpec: {"age_min": int, "age_max": int,
          "gender_concept_ids": [int]}  — all fields optional

        EndStrategySpec: {"type": "observation_end"|"date_offset"|"drug_era",
          "offset_days": int, "drug_concept_set": "<name>", "gap_days": int}

        Domain-specific attributes can be added to primary_criteria,
        inclusion_rules, or exclusion_criteria via the "attributes" field:
        [
          {"type": "value_as_number", "op": "gte", "value": 9.0},
          {"type": "unit", "concept_ids": [8713]},
          {"type": "days_supply", "op": "gte", "value": 90},
          {"type": "quantity", "op": "bt", "value": 1, "extent": 10},
          {"type": "refills", "op": "gte", "value": 2},
          {"type": "visit_type", "concept_ids": [9201]},
          {"type": "age", "op": "gte", "value": 18},
          {"type": "gender", "concept_ids": [8507]}
        ]
        Numeric ops: gt, gte, lt, lte, eq, bt (between — requires extent).
        Concept attrs take concept_ids (list of OMOP concept IDs).
        Domain validation rejects invalid combinations (e.g., value_as_number
        on Condition raises an error).

        Output fields:
        - success: whether the definition was built successfully
        - cohort_json: the CIRCE JSON (when compile=False and execute=False)
        - validation: semantic validation results
        - concept_set_mapping: name → CodesetId mapping
        - summary: human-readable description
        - compiled (if compile=True only): compilation result with SQL
        - materialization (if execute=True): summary with cohort_definition_id,
          subject_count, date ranges — NOT individual patient rows

        Args:
            spec_json: Builder specification as a JSON string
            compile: If True, compile the built definition to SQL.
            execute: If True, compile + persist to results.cohort (implies compile=True).
            dialect: Target SQL dialect for compilation. Default 'duckdb'.
            cdm_schema: Schema with OMOP CDM clinical tables. Default 'main_cdm'.
            vocab_schema: Schema with vocabulary tables. Default 'main_vocab'.
            results_schema: Schema for the output cohort table.
        """
        result = build_cohort(spec_json)

        if not result.get("success") or (not compile and not execute):
            return json.dumps(result, indent=2)

        if not execute:
            # compile-only path (no materialization)
            compile_result = compile_cohort(
                result["cohort_json"],
                dialect=dialect,
                cdm_schema=cdm_schema,
                vocab_schema=vocab_schema,
                results_schema=results_schema,
            )
            result["compiled"] = compile_result
            return json.dumps(result, indent=2)

        # execute=True: get next ID before compilation (ID is baked into SQL)
        try:
            with get_rw_connection() as conn:
                cohort_id = next_cohort_definition_id(conn, schema=results_schema)
        except Exception as e:
            result["error"] = f"Failed to allocate cohort ID: {e}"
            return json.dumps(result, indent=2)

        compile_result = compile_cohort(
            result["cohort_json"],
            dialect=dialect,
            cdm_schema=cdm_schema,
            vocab_schema=vocab_schema,
            results_schema=results_schema,
            cohort_definition_id=cohort_id,
        )

        if not compile_result.get("success"):
            result["compiled"] = compile_result
            return json.dumps(result, indent=2)

        # Materialize cohort to results.cohort
        mat_result = _materialize_cohort(
            segments=compile_result["segments"],
            results_schema=results_schema,
            cohort_definition_id=cohort_id,
            source_identifier="build_cohort_definition",
        )

        # Return compact summary (no segments/sql to avoid flooding context)
        return json.dumps({
            "success": True,
            "materialization": mat_result,
            "concept_set_mapping": result.get("concept_set_mapping"),
            "summary": result.get("summary"),
            "complexity": compile_result.get("complexity"),
            "warnings": compile_result.get("warnings"),
            "validation": compile_result.get("validation"),
        }, indent=2)

    @mcp.resource("circe://schema/cohort-definition")
    def cohort_definition_schema() -> str:
        """Structure reference for OHDSI CIRCE cohort definition JSON."""
        return """# CIRCE Cohort Definition JSON Structure

A cohort definition describes a group of patients meeting specific
clinical criteria. This is the standard format used by OHDSI ATLAS,
the Phenotype Library, and this compiler.

## Top-Level Structure

```json
{
  "ConceptSets": [...],          // Reusable sets of clinical concepts
  "PrimaryCriteria": {...},      // Initial qualifying events
  "AdditionalCriteria": {...},   // Optional: further criteria on primary events
  "QualifiedLimit": {...},       // How to pick among multiple qualifying events
  "ExpressionLimit": {...},      // How to pick among events passing all rules
  "InclusionRules": [...],       // Additional filtering rules
  "EndStrategy": {...},          // When cohort membership ends
  "CensoringCriteria": [...],    // Events that end membership early
  "CollapseSettings": {...}      // How to merge overlapping eras
}
```

## ConceptSets

Each concept set defines a group of OMOP concepts:

```json
{
  "id": 0,
  "name": "Type 2 Diabetes",
  "expression": {
    "items": [
      {
        "concept": {
          "CONCEPT_ID": 201826,
          "CONCEPT_NAME": "Type 2 diabetes mellitus",
          "DOMAIN_ID": "Condition",
          "VOCABULARY_ID": "SNOMED",
          "CONCEPT_CLASS_ID": "Clinical Finding",
          "STANDARD_CONCEPT": "S",
          "CONCEPT_CODE": "44054006"
        },
        "isExcluded": false,
        "includeDescendants": true,
        "includeMapped": false
      }
    ]
  }
}
```

- Use vocabulary tools (search_concepts, preview_concept_set) to find
  the right concept_ids and verify descendant expansion before building
  the definition.

## PrimaryCriteria

Defines the index event that qualifies a patient:

```json
{
  "PrimaryCriteria": {
    "CriteriaList": [
      {
        "ConditionOccurrence": {
          "CodesetId": 0
        }
      }
    ],
    "ObservationWindow": {
      "PriorDays": 365,
      "PostDays": 0
    },
    "PrimaryCriteriaLimit": {
      "Type": "First"
    }
  }
}
```

### Supported Criteria Types
- ConditionOccurrence: Diagnosis/condition events
- DrugExposure: Medication events
- ProcedureOccurrence: Procedure events
- Measurement: Lab/vital sign events
- Observation: Clinical observation events
- VisitOccurrence: Healthcare encounter events
- Death: Death events
- DeviceExposure: Medical device events
- ConditionEra: Aggregated condition periods
- DrugEra: Aggregated drug periods

## InclusionRules

Filter patients with additional requirements:

```json
{
  "InclusionRules": [
    {
      "name": "Has prior metformin",
      "expression": {
        "Type": "ALL",
        "CriteriaList": [
          {
            "Criteria": {
              "DrugExposure": {
                "CodesetId": 1
              }
            },
            "StartWindow": {
              "Start": {"Days": 365, "Coeff": -1},
              "End": {"Days": 0, "Coeff": -1}
            },
            "Occurrence": {
              "Type": 2,
              "Count": 1
            }
          }
        ]
      }
    }
  ]
}
```

## EndStrategy

When cohort membership ends. Options:
- null: End of continuous observation (default)
- DateOffset: Fixed offset from event date
- CustomEra: Drug era-based end

## CollapseSettings

```json
{
  "CollapseSettings": {
    "CollapseType": "ERA",
    "EraPad": 0
  }
}
```

## Minimal Working Example

```json
{
  "ConceptSets": [
    {
      "id": 0,
      "name": "Type 2 Diabetes",
      "expression": {
        "items": [
          {
            "concept": {
              "CONCEPT_ID": 201826,
              "CONCEPT_NAME": "Type 2 diabetes mellitus",
              "DOMAIN_ID": "Condition",
              "VOCABULARY_ID": "SNOMED",
              "CONCEPT_CLASS_ID": "Clinical Finding",
              "STANDARD_CONCEPT": "S",
              "CONCEPT_CODE": "44054006"
            },
            "isExcluded": false,
            "includeDescendants": true,
            "includeMapped": false
          }
        ]
      }
    }
  ],
  "PrimaryCriteria": {
    "CriteriaList": [
      {
        "ConditionOccurrence": {
          "CodesetId": 0
        }
      }
    ],
    "ObservationWindow": {
      "PriorDays": 365,
      "PostDays": 0
    },
    "PrimaryCriteriaLimit": {
      "Type": "First"
    }
  },
  "QualifiedLimit": {"Type": "First"},
  "ExpressionLimit": {"Type": "First"},
  "InclusionRules": [],
  "EndStrategy": null,
  "CensoringCriteria": [],
  "CollapseSettings": {
    "CollapseType": "ERA",
    "EraPad": 0
  }
}
```
"""

    @mcp.resource("circe://schema/builder-spec")
    def builder_spec_schema() -> str:
        """Builder spec reference for build_cohort_definition: simplified format with all nested model shapes and examples."""
        return """# Builder Spec Reference for build_cohort_definition

The `build_cohort_definition` tool accepts a simplified JSON spec that is
converted to valid CIRCE JSON. This document describes every nested model
and provides worked examples.

## Top-Level: CohortDefinitionSpec

```json
{
  "concept_sets": [ConceptSetSpec, ...],       // Required, min 1
  "primary_criteria": PrimaryCriteriaSpec,     // Required
  "inclusion_rules": [InclusionRuleSpec, ...], // Optional
  "exclusion_criteria": [ExclusionCriterionSpec, ...], // Optional
  "observation_window": TemporalSpec,          // Optional
  "end_strategy": EndStrategySpec,             // Optional
  "qualified_limit": "First" | "All" | "Last", // Default "First"
  "collapse_era_pad": int                      // Default 0
}
```

## Nested Model Shapes

### ConceptSetSpec
```json
{
  "name": "Type 2 Diabetes",
  "domain": "Condition",
  "concepts": [
    {"concept_id": 201826, "include_descendants": true,
     "is_excluded": false, "include_mapped": false}
  ]
}
```
domain: Condition, Drug, Procedure, Measurement, Observation, Visit,
  Death, Device, Specimen, Condition Era, Drug Era, Dose Era, Visit Detail,
  Observation Period

### PrimaryCriteriaSpec
```json
{"concept_set": "<name>", "first_occurrence": true, "attributes": []}
```

### InclusionRuleSpec
```json
{
  "name": "On Metformin",
  "concept_set": "<name>",
  "temporal": {"days_before": 365, "days_after": 0},
  "occurrence": {"type": "at_least", "count": 1},
  "demographic": {"age_min": 18, "age_max": 65, "gender_concept_ids": [8507]},
  "attributes": []
}
```
All fields except name and concept_set are optional.

### ExclusionCriterionSpec
```json
{"name": "No prior CKD", "concept_set": "<name>",
 "temporal": {"days_before": 99999, "days_after": 0},
 "attributes": []}
```
Converted internally to an inclusion rule with exactly 0 occurrences.
temporal and attributes are optional.

### TemporalSpec
```json
{"days_before": 365, "days_after": 0}
```
days_before: look back N days from index. days_after: look forward N days.

### OccurrenceSpec
```json
{"type": "at_least", "count": 1}
```
type: "at_least" | "at_most" | "exactly"

### DemographicSpec
```json
{"age_min": 18, "age_max": 65, "gender_concept_ids": [8507, 8532]}
```
All fields optional. gender concept IDs: 8507=Male, 8532=Female.

### EndStrategySpec
```json
{"type": "observation_end"}
{"type": "date_offset", "offset_days": 30, "date_field": "StartDate"}
{"type": "drug_era", "drug_concept_set": "<name>", "gap_days": 30, "offset_days": 0}
```

### AttributeSpec (discriminated union on "type")
```json
{"type": "value_as_number", "op": "gte", "value": 9.0}
{"type": "unit", "concept_ids": [8713]}
{"type": "days_supply", "op": "gte", "value": 90}
{"type": "quantity", "op": "bt", "value": 1, "extent": 10}
{"type": "refills", "op": "gte", "value": 2}
{"type": "visit_type", "concept_ids": [9201]}
{"type": "age", "op": "gte", "value": 18}
{"type": "gender", "concept_ids": [8507]}
```
Numeric ops: gt, gte, lt, lte, eq, bt (between — requires extent).

## Worked Examples

### Example 1: Minimal (single condition)
```json
{
  "concept_sets": [
    {"name": "Type 2 Diabetes", "domain": "Condition",
     "concepts": [{"concept_id": 201826, "include_descendants": true}]}
  ],
  "primary_criteria": {"concept_set": "Type 2 Diabetes", "first_occurrence": true},
  "observation_window": {"days_before": 365, "days_after": 0}
}
```

### Example 2: Exclusion (HTN excluding CKD)
```json
{
  "concept_sets": [
    {"name": "HTN", "domain": "Condition",
     "concepts": [{"concept_id": 316866, "include_descendants": true}]},
    {"name": "CKD", "domain": "Condition",
     "concepts": [{"concept_id": 46271022, "include_descendants": true}]}
  ],
  "primary_criteria": {"concept_set": "HTN", "first_occurrence": true},
  "observation_window": {"days_before": 365, "days_after": 0},
  "exclusion_criteria": [
    {"name": "No prior CKD", "concept_set": "CKD"}
  ]
}
```

### Example 3: Inclusion + demographics (T2DM + Metformin, age 18-65)
```json
{
  "concept_sets": [
    {"name": "T2DM", "domain": "Condition",
     "concepts": [{"concept_id": 201826, "include_descendants": true}]},
    {"name": "Metformin", "domain": "Drug",
     "concepts": [{"concept_id": 1503297, "include_descendants": true}]}
  ],
  "primary_criteria": {"concept_set": "T2DM", "first_occurrence": true},
  "observation_window": {"days_before": 365, "days_after": 0},
  "inclusion_rules": [
    {"name": "On Metformin", "concept_set": "Metformin",
     "temporal": {"days_before": 365, "days_after": 0},
     "occurrence": {"type": "at_least", "count": 1},
     "demographic": {"age_min": 18, "age_max": 65}}
  ]
}
```
"""

    return mcp
