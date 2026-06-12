"""Gold-standard cohort definitions and execution accuracy scorer.

Tier A: SQL execution validity — does the agent's SQL run and return rows?
Tier B: Gold-standard comparison — Jaccard/F1 against reference patient sets.

Usage:
    # Generate gold-standard reference sets (run once after 100K rebuild)
    uv run python gold_standards.py generate --db /path/to/synthea_omop_etl.duckdb

    # Score a result CSV with execution accuracy
    uv run python gold_standards.py score --db /path/to/synthea_omop_etl.duckdb --csv results/anthropic/claude_sonnet_4/20260221T034159Z.csv

    # Score all result CSVs
    uv run python gold_standards.py score-all --db /path/to/synthea_omop_etl.duckdb
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]

from scorers import (
    GOLD_STANDARD_PROMPTS,
    SQL_GENERATING_PROMPTS,
    get_args_for_tool,
    get_result_for_tool,
    has_tool,
    parse_tool_arguments,
    parse_tool_results,
    parse_tools_called,
)

# ── Constants ────────────────────────────────────────────────────────────

VOCAB_SCHEMA = "main_vocab"
CDM_SCHEMA = "main_cdm"
RESULTS_DIR = Path(__file__).parent / "results"
REFERENCE_DIR = Path(__file__).parent / "gold_standard_references"

# Default DuckDB path (repo root; pass --db to override)
DEFAULT_DB = Path(__file__).parents[1] / "synthea_omop_etl.duckdb"


# ── Gold-standard query definitions ─────────────────────────────────────

@dataclass
class GoldStandard:
    """A gold-standard cohort definition for a specific prompt."""
    prompt_id: int
    description: str
    reference_sql: str
    result_type: str  # "patient_set" or "ranked_list"
    comparison_metric: str  # "jaccard_f1" or "rank_correlation"


# Type 2 Diabetes standard concept set (concept 201826 + descendants)
_T2DM_CONCEPT_SET_SQL = f"""
    SELECT ca.descendant_concept_id AS concept_id
    FROM {VOCAB_SCHEMA}.concept_ancestor ca
    WHERE ca.ancestor_concept_id = 201826
    UNION
    SELECT 201826 AS concept_id
"""

# Essential hypertension concept set (concept 320128 + descendants)
_HTN_CONCEPT_SET_SQL = f"""
    SELECT ca.descendant_concept_id AS concept_id
    FROM {VOCAB_SCHEMA}.concept_ancestor ca
    WHERE ca.ancestor_concept_id = 320128
    UNION
    SELECT 320128 AS concept_id
"""

# Chronic kidney disease concept set (concept 46271022 + descendants)
_CKD_CONCEPT_SET_SQL = f"""
    SELECT ca.descendant_concept_id AS concept_id
    FROM {VOCAB_SCHEMA}.concept_ancestor ca
    WHERE ca.ancestor_concept_id = 46271022
    UNION
    SELECT 46271022 AS concept_id
"""

# Metformin drug concept set (concept 1503297 + descendants)
_METFORMIN_CONCEPT_SET_SQL = f"""
    SELECT ca.descendant_concept_id AS concept_id
    FROM {VOCAB_SCHEMA}.concept_ancestor ca
    WHERE ca.ancestor_concept_id = 1503297
    UNION
    SELECT 1503297 AS concept_id
"""

GOLD_STANDARDS: dict[int, GoldStandard] = {
    # P19: How many patients have Type 2 Diabetes in our database?
    19: GoldStandard(
        prompt_id=19,
        description="Patients with T2DM (concept 201826 + descendants) in condition_occurrence",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            WHERE co.condition_concept_id IN ({_T2DM_CONCEPT_SET_SQL})
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),

    # P21: Write a query to find all diabetes conditions using standard concepts
    21: GoldStandard(
        prompt_id=21,
        description="Diabetes condition records using standard concepts (same T2DM set)",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            WHERE co.condition_concept_id IN ({_T2DM_CONCEPT_SET_SQL})
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),

    # P24: What are the top 10 most common conditions in our database?
    24: GoldStandard(
        prompt_id=24,
        description="Top 10 condition_concept_ids by occurrence count",
        reference_sql=f"""
            SELECT
                co.condition_concept_id,
                c.concept_name,
                COUNT(*) AS occurrence_count
            FROM {CDM_SCHEMA}.condition_occurrence co
            JOIN {VOCAB_SCHEMA}.concept c ON co.condition_concept_id = c.concept_id
            GROUP BY co.condition_concept_id, c.concept_name
            ORDER BY occurrence_count DESC
            LIMIT 10
        """,
        result_type="ranked_list",
        comparison_metric="rank_correlation",
    ),

    # P15: Find a heart failure phenotype and compile it to SQL
    # Note: The gold standard here depends on which phenotype the agent retrieves.
    # We use heart failure concept 316139 + descendants as the reference cohort.
    15: GoldStandard(
        prompt_id=15,
        description="Patients with heart failure (concept 316139 + descendants)",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            WHERE co.condition_concept_id IN (
                SELECT ca.descendant_concept_id
                FROM {VOCAB_SCHEMA}.concept_ancestor ca
                WHERE ca.ancestor_concept_id = 316139
                UNION
                SELECT 316139
            )
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),

    # P31: First T2DM diagnosis with 365 days prior observation
    31: GoldStandard(
        prompt_id=31,
        description="First T2DM diagnosis with >=365 days prior observation",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            JOIN {CDM_SCHEMA}.observation_period op
                ON co.person_id = op.person_id
            WHERE co.condition_concept_id IN ({_T2DM_CONCEPT_SET_SQL})
              AND co.condition_start_date >= op.observation_period_start_date + INTERVAL '365' DAY
              AND co.condition_start_date <= op.observation_period_end_date
              AND co.condition_start_date = (
                  SELECT MIN(co2.condition_start_date)
                  FROM {CDM_SCHEMA}.condition_occurrence co2
                  WHERE co2.person_id = co.person_id
                    AND co2.condition_concept_id IN ({_T2DM_CONCEPT_SET_SQL})
              )
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),

    # P32: Hypertension excluding patients with prior CKD
    32: GoldStandard(
        prompt_id=32,
        description="Hypertension patients excluding those with prior CKD",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            WHERE co.condition_concept_id IN ({_HTN_CONCEPT_SET_SQL})
              AND co.person_id NOT IN (
                  SELECT co2.person_id
                  FROM {CDM_SCHEMA}.condition_occurrence co2
                  WHERE co2.condition_concept_id IN ({_CKD_CONCEPT_SET_SQL})
                    AND co2.condition_start_date < co.condition_start_date
              )
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),

    # P33: T2DM patients aged 18-65 with Metformin within 365 days before diagnosis
    33: GoldStandard(
        prompt_id=33,
        description="T2DM aged 18-65 with Metformin within 365 days before diagnosis",
        reference_sql=f"""
            SELECT DISTINCT co.person_id
            FROM {CDM_SCHEMA}.condition_occurrence co
            JOIN {CDM_SCHEMA}.person p ON co.person_id = p.person_id
            JOIN {CDM_SCHEMA}.drug_exposure de ON co.person_id = de.person_id
            WHERE co.condition_concept_id IN ({_T2DM_CONCEPT_SET_SQL})
              AND de.drug_concept_id IN ({_METFORMIN_CONCEPT_SET_SQL})
              AND de.drug_exposure_start_date
                  BETWEEN co.condition_start_date - INTERVAL '365' DAY
                      AND co.condition_start_date
              AND (EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth)
                  BETWEEN 18 AND 65
        """,
        result_type="patient_set",
        comparison_metric="jaccard_f1",
    ),
}


# ── Database helpers ─────────────────────────────────────────────────────

def connect_db(db_path: Path) -> "duckdb.DuckDBPyConnection":
    """Connect to DuckDB in read-only mode."""
    if duckdb is None:
        print("ERROR: duckdb not installed. Run: uv add duckdb")
        sys.exit(1)
    return duckdb.connect(str(db_path), read_only=True)


def execute_sql(conn: "duckdb.DuckDBPyConnection", sql: str) -> list[tuple] | None:
    """Execute SQL and return results, or None on error."""
    try:
        result = conn.execute(sql)
        return result.fetchall()
    except Exception as e:
        return None


def extract_person_ids(rows: list[tuple]) -> set[int]:
    """Extract person_ids from query results (assumes first column is person_id)."""
    return {int(row[0]) for row in rows if row[0] is not None}


# ── Metrics ──────────────────────────────────────────────────────────────

@dataclass
class ComparisonResult:
    """Result of comparing agent output to gold standard."""
    prompt_id: int
    execution_valid: str  # VALID, INVALID, ERROR, N/A
    agent_sql: str = ""
    agent_row_count: int = 0
    reference_row_count: int = 0
    jaccard: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    rank_correlation: float | None = None
    exact_match_rate: float | None = None
    error_message: str = ""


def jaccard_index(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity index."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def precision_recall_f1(predicted: set, reference: set) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for patient set comparison."""
    if not predicted and not reference:
        return 1.0, 1.0, 1.0
    if not predicted:
        return 0.0, 0.0, 0.0
    if not reference:
        return 0.0, 0.0, 0.0

    tp = len(predicted & reference)
    fp = len(predicted - reference)
    fn = len(reference - predicted)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1


def rank_overlap(agent_list: list, reference_list: list, k: int = 10) -> float:
    """Compute overlap at k between two ranked lists of concept_ids."""
    agent_set = set(agent_list[:k])
    ref_set = set(reference_list[:k])
    if not ref_set:
        return 0.0
    return len(agent_set & ref_set) / len(ref_set)


# ── SQL extraction from tool arguments ───────────────────────────────────

def extract_agent_sql(tools: list[str], arguments: list[dict]) -> str | None:
    """Extract the SQL query from the agent's Select_Query tool call."""
    args = get_args_for_tool(tools, arguments, "Select_Query")
    if args is None:
        return None

    for param in ("sql", "query", "statement"):
        val = args.get(param)
        if val and isinstance(val, str):
            return val

    return None


def extract_guided_person_ids(
    tools: list[str],
    tool_results: list[dict],
) -> set[int] | None:
    """Extract person_ids from compile_cohort_definition tool_result in guided condition.

    When compile_cohort_definition is called with execute=True, its tool_result
    contains execution output with person_ids. Parse them directly — no need to
    re-execute SQL.

    Returns a set of person_ids, or None if no usable result found.
    """
    if not has_tool(tools, "compile_cohort_definition"):
        return None

    result_str = get_result_for_tool(tool_results, "compile_cohort_definition")
    if result_str is None:
        return None

    # The result may be a JSON string or already a dict-like string
    try:
        result_data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None

    # Handle various result shapes from compile_cohort_definition(execute=True):
    # Shape 1: {"execution_result": {"rows": [[person_id, ...], ...], ...}}
    # Shape 2: {"execution_result": [{"person_id": 123}, ...]}
    # Shape 3: {"person_ids": [123, 456, ...]}
    # Shape 4: {"result": {"person_ids": [...]}} or similar nesting

    if not isinstance(result_data, dict):
        return None

    person_ids: set[int] = set()

    # Direct person_ids key
    if "person_ids" in result_data:
        ids = result_data["person_ids"]
        if isinstance(ids, list):
            return {int(pid) for pid in ids if _is_int_like(pid)}

    # execution_result with rows (tabular format)
    exec_result = result_data.get("execution_result", result_data.get("result"))
    if exec_result is None:
        return None

    if isinstance(exec_result, dict):
        # {"rows": [[id1], [id2], ...], "columns": ["person_id", ...]}
        rows = exec_result.get("rows", [])
        columns = exec_result.get("columns", [])
        if rows and isinstance(rows, list):
            # Find person_id column index
            pid_idx = 0
            for i, col in enumerate(columns):
                if isinstance(col, str) and "person_id" in col.lower():
                    pid_idx = i
                    break
            for row in rows:
                if isinstance(row, (list, tuple)) and len(row) > pid_idx:
                    val = row[pid_idx]
                    if _is_int_like(val):
                        person_ids.add(int(val))
            if person_ids:
                return person_ids

        # {"person_ids": [...]} nested in execution_result
        if "person_ids" in exec_result:
            ids = exec_result["person_ids"]
            if isinstance(ids, list):
                return {int(pid) for pid in ids if _is_int_like(pid)}

    elif isinstance(exec_result, list):
        # List of dicts: [{"person_id": 123}, ...]
        for item in exec_result:
            if isinstance(item, dict):
                for key in ("person_id", "PERSON_ID", "subject_id", "SUBJECT_ID"):
                    val = item.get(key)
                    if val is not None and _is_int_like(val):
                        person_ids.add(int(val))
                        break
            elif _is_int_like(item):
                person_ids.add(int(item))
        if person_ids:
            return person_ids

    return person_ids if person_ids else None


def _is_int_like(val) -> bool:
    """Check if a value can be safely converted to int."""
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


# ── Generate reference sets ──────────────────────────────────────────────

def generate_references(db_path: Path) -> None:
    """Run gold-standard queries and save reference results."""
    conn = connect_db(db_path)
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

    for pid, gs in sorted(GOLD_STANDARDS.items()):
        print(f"P{pid}: {gs.description}")
        rows = execute_sql(conn, gs.reference_sql)

        if rows is None:
            print(f"  ERROR: query failed")
            continue

        print(f"  Rows: {len(rows)}")

        # Save reference
        ref_path = REFERENCE_DIR / f"P{pid:02d}_reference.json"
        if gs.result_type == "patient_set":
            person_ids = sorted(extract_person_ids(rows))
            ref_data = {
                "prompt_id": pid,
                "description": gs.description,
                "result_type": gs.result_type,
                "patient_count": len(person_ids),
                "person_ids": person_ids,
            }
        elif gs.result_type == "ranked_list":
            ranked = [
                {"concept_id": int(r[0]), "concept_name": r[1], "count": int(r[2])}
                for r in rows
            ]
            ref_data = {
                "prompt_id": pid,
                "description": gs.description,
                "result_type": gs.result_type,
                "ranked_items": ranked,
            }
        else:
            continue

        ref_path.write_text(json.dumps(ref_data, indent=2), encoding="utf-8")
        print(f"  Saved: {ref_path}")

    conn.close()
    print(f"\nReference sets saved to: {REFERENCE_DIR}")


# ── Score execution accuracy ─────────────────────────────────────────────

def score_execution(
    row: dict,
    conn: "duckdb.DuckDBPyConnection",
) -> ComparisonResult:
    """Score a single result row for execution accuracy.

    Supports two paths:
      - Open condition: extract SQL from Select_Query tool arguments → re-execute
      - Guided condition: extract person_ids from compile_cohort_definition tool_result
    """
    prompt_id = int(row.get("prompt_id", 0))
    tools = parse_tools_called(row.get("tools_called", ""))
    arguments = parse_tool_arguments(row.get("tool_arguments", ""))
    tool_results = parse_tool_results(row.get("tool_results", ""))
    condition = row.get("condition", "open")

    result = ComparisonResult(prompt_id=prompt_id, execution_valid="N/A")

    # Only score SQL-generating prompts
    if prompt_id not in SQL_GENERATING_PROMPTS:
        return result

    # ── Guided condition path: extract person_ids from tool_result ──────
    guided_ids = None
    if condition == "guided" and prompt_id in GOLD_STANDARD_PROMPTS:
        guided_ids = extract_guided_person_ids(tools, tool_results)
        if guided_ids is not None:
            result.execution_valid = "VALID"
            result.agent_row_count = len(guided_ids)

            gs = GOLD_STANDARDS.get(prompt_id)
            ref_path = REFERENCE_DIR / f"P{prompt_id:02d}_reference.json"

            if gs and ref_path.exists() and gs.result_type == "patient_set":
                ref_data = json.loads(ref_path.read_text(encoding="utf-8"))
                ref_ids = set(ref_data["person_ids"])
                result.reference_row_count = len(ref_ids)
                result.jaccard = round(jaccard_index(guided_ids, ref_ids), 4)
                p, r, f1 = precision_recall_f1(guided_ids, ref_ids)
                result.precision = round(p, 4)
                result.recall = round(r, 4)
                result.f1 = round(f1, 4)

            return result

        # Guided but no compile_cohort_definition result found — check for
        # Select_Query fallback (some models may still use it)

    # ── Open condition path: extract SQL from Select_Query ────────────
    agent_sql = extract_agent_sql(tools, arguments)
    if agent_sql is None:
        if condition == "guided":
            result.error_message = "no compile_cohort_definition result or Select_Query found"
        else:
            result.error_message = "no Select_Query tool call found"
        return result

    result.agent_sql = agent_sql

    # Tier A: Execute the agent's SQL
    agent_rows = execute_sql(conn, agent_sql)
    if agent_rows is None:
        result.execution_valid = "ERROR"
        result.error_message = "SQL execution failed"
        return result

    result.agent_row_count = len(agent_rows)

    if len(agent_rows) == 0:
        result.execution_valid = "INVALID"
        result.error_message = "query returned 0 rows"
        return result

    result.execution_valid = "VALID"

    # Tier B: Gold-standard comparison (only for select prompts)
    if prompt_id in GOLD_STANDARD_PROMPTS:
        gs = GOLD_STANDARDS.get(prompt_id)
        ref_path = REFERENCE_DIR / f"P{prompt_id:02d}_reference.json"

        if gs and ref_path.exists():
            ref_data = json.loads(ref_path.read_text(encoding="utf-8"))

            if gs.result_type == "patient_set":
                ref_ids = set(ref_data["person_ids"])
                agent_ids = extract_person_ids(agent_rows)
                result.reference_row_count = len(ref_ids)
                result.jaccard = round(jaccard_index(agent_ids, ref_ids), 4)
                p, r, f1 = precision_recall_f1(agent_ids, ref_ids)
                result.precision = round(p, 4)
                result.recall = round(r, 4)
                result.f1 = round(f1, 4)

            elif gs.result_type == "ranked_list":
                ref_ranked = [item["concept_id"] for item in ref_data["ranked_items"]]
                # Extract concept_ids from agent results (assume first column)
                agent_ranked = [int(r[0]) for r in agent_rows if r[0] is not None]
                result.reference_row_count = len(ref_ranked)
                result.exact_match_rate = round(rank_overlap(agent_ranked, ref_ranked), 4)

    return result


def score_csv_execution(
    csv_path: Path,
    conn: "duckdb.DuckDBPyConnection",
    dry_run: bool = False,
) -> list[ComparisonResult]:
    """Score all rows in a CSV for execution accuracy."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        original_fields = list(reader.fieldnames)
        rows = list(reader)

    results = []
    for row in rows:
        comp = score_execution(row, conn)
        results.append(comp)

        # Update the row with execution results
        row["execution_valid"] = comp.execution_valid
        if comp.jaccard is not None:
            row["jaccard"] = comp.jaccard
            row["f1"] = comp.f1
        if comp.exact_match_rate is not None:
            row["rank_overlap"] = comp.exact_match_rate
        if comp.error_message:
            existing_notes = row.get("notes", "")
            row["notes"] = f"{existing_notes} | [exec] {comp.error_message}".strip(" |")

    if not dry_run:
        # Write back with execution columns
        fieldnames = list(original_fields)
        new_cols = ["execution_valid", "jaccard", "f1", "rank_overlap"]
        for col in new_cols:
            if col not in fieldnames:
                fieldnames.append(col)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    return results


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gold-standard execution accuracy scorer.",
    )
    sub = parser.add_subparsers(dest="command")

    # generate subcommand
    gen = sub.add_parser("generate", help="Generate gold-standard reference sets")
    gen.add_argument("--db", default=str(DEFAULT_DB), help="Path to DuckDB file")

    # score subcommand
    sc = sub.add_parser("score", help="Score a single result CSV")
    sc.add_argument("--db", default=str(DEFAULT_DB), help="Path to DuckDB file")
    sc.add_argument("--csv", required=True, help="Path to result CSV")
    sc.add_argument("--dry-run", action="store_true")

    # score-all subcommand
    sa = sub.add_parser("score-all", help="Score all result CSVs")
    sa.add_argument("--db", default=str(DEFAULT_DB), help="Path to DuckDB file")
    sa.add_argument("--results-dir", default=str(RESULTS_DIR))
    sa.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "generate":
        generate_references(Path(args.db))

    elif args.command == "score":
        conn = connect_db(Path(args.db))
        results = score_csv_execution(Path(args.csv), conn, dry_run=args.dry_run)
        conn.close()

        valid = sum(1 for r in results if r.execution_valid == "VALID")
        error = sum(1 for r in results if r.execution_valid == "ERROR")
        invalid = sum(1 for r in results if r.execution_valid == "INVALID")
        gold = [r for r in results if r.jaccard is not None]

        print(f"Execution: {valid} VALID, {error} ERROR, {invalid} INVALID")
        if gold:
            avg_jaccard = sum(r.jaccard for r in gold) / len(gold)
            avg_f1 = sum(r.f1 for r in gold) / len(gold)
            print(f"Gold-standard (n={len(gold)}): mean Jaccard={avg_jaccard:.3f}, mean F1={avg_f1:.3f}")

    elif args.command == "score-all":
        conn = connect_db(Path(args.db))
        results_dir = Path(args.results_dir)
        skip = {"result_provenance.csv", "flagged_for_review.csv"}

        all_results = []
        for csv_path in sorted(results_dir.rglob("*.csv")):
            if csv_path.name in skip or csv_path.name.startswith("."):
                continue
            print(f"Scoring: {csv_path.relative_to(results_dir)}")
            results = score_csv_execution(csv_path, conn, dry_run=args.dry_run)
            all_results.extend(results)

            valid = sum(1 for r in results if r.execution_valid == "VALID")
            print(f"  {valid}/{len(results)} SQL executions valid")

        conn.close()

        # Summary
        sql_results = [r for r in all_results if r.execution_valid != "N/A"]
        if sql_results:
            valid = sum(1 for r in sql_results if r.execution_valid == "VALID")
            print(f"\nTotal: {valid}/{len(sql_results)} SQL executions valid")

        gold = [r for r in all_results if r.jaccard is not None]
        if gold:
            avg_jaccard = sum(r.jaccard for r in gold) / len(gold)
            avg_f1 = sum(r.f1 for r in gold) / len(gold)
            print(f"Gold-standard (n={len(gold)}): mean Jaccard={avg_jaccard:.3f}, mean F1={avg_f1:.3f}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
