"""Automated scorer for OHDSI Agent evaluation results.

Reads result CSVs, applies codebook rules to each row, and writes:
  1. Updated CSVs with filled result + parameters_correct + failure_mode columns
  2. flagged_for_review.csv — rows that need manual review
  3. scoring_summary.md — pass rates by model, category, prompt, failure modes

Usage:
    uv run python score_results.py
    uv run python score_results.py --results-dir results/
    uv run python score_results.py --dry-run          # preview without writing
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

csv.field_size_limit(10_000_000)  # tool_results can exceed the 128KB default
from pathlib import Path

from codebook import get_rule
from scorers import (
    FAILURE_MODES,
    SQL_GENERATING_PROMPTS,
    classify_failure,
    parse_tool_arguments,
    parse_tools_called,
)

RESULTS_DIR = Path(__file__).parent / "results"


def find_result_csvs(results_dir: Path) -> list[Path]:
    """Find all result CSV files (recursive, skip provenance and flagged)."""
    skip = {"result_provenance.csv", "flagged_for_review.csv"}
    csvs = []
    for p in sorted(results_dir.rglob("*.csv")):
        if p.name in skip or p.name.startswith("."):
            continue
        csvs.append(p)
    return csvs


def score_row(row: dict) -> dict:
    """Apply codebook rules to a single result row.

    Returns the row with result, parameters_correct, failure_mode, and notes updated.
    Does NOT overwrite existing manual scores.
    """
    prompt_id = int(row.get("prompt_id", 0))
    rule = get_rule(prompt_id)

    if rule is None:
        row.setdefault("auto_score_notes", f"no rule for prompt_id={prompt_id}")
        return row

    # Parse tool data
    tools = parse_tools_called(row.get("tools_called", ""))
    arguments = parse_tool_arguments(row.get("tool_arguments", ""))

    # Check for timeout / max-rounds FAIL
    errors = row.get("errors", "")
    if "timeout" in errors.lower():
        row["result"] = row.get("result") or "FAIL"
        row["parameters_correct"] = row.get("parameters_correct") or "N/A"
        row["failure_mode"] = row.get("failure_mode") or "TIMEOUT"
        row.setdefault("auto_score_notes", "timeout")
        return row

    # Empty tools + no errors: check for text-only response
    if not tools and not errors:
        existing = row.get("result", "").strip()
        if not existing:
            row["result"] = "FAIL"
            row["parameters_correct"] = "N/A"
            row["failure_mode"] = "TOOL_OMISSION"
            row.setdefault("auto_score_notes", "no tools called, no errors")
        return row

    # Apply rule
    score = rule.evaluate(tools, arguments)

    needs_review = score.get("needs_review", False)

    if needs_review and row.get("reviewed", "").strip() != "true":
        # Store auto-score provisionally; blank result as review gate
        if not row.get("provisional_result", "").strip():
            row["provisional_result"] = score["result"]
        if not row.get("provisional_params", "").strip():
            row["provisional_params"] = score["parameters_correct"]
        # Clear any pre-existing result to enforce the gate
        row["result"] = ""
        row["parameters_correct"] = ""
    else:
        # Not flagged, or already reviewed: write final score as before
        if not row.get("result", "").strip():
            row["result"] = score["result"]
        if not row.get("parameters_correct", "").strip():
            row["parameters_correct"] = score["parameters_correct"]

    # Classify failure modes (use effective result for provisional rows)
    effective_result = row.get("result", "").strip() or row.get("provisional_result", "").strip()
    if not row.get("failure_mode", "").strip():
        if effective_result in ("FAIL", "PARTIAL"):
            # Parse expected tools from the expected_tools column
            expected_raw = row.get("expected_tools", "")
            expected_tools = [
                t.strip() for t in expected_raw.replace("→", ",").replace("+", ",").split(",")
                if t.strip() and not t.strip().startswith("(") and "=" not in t.strip()
            ]
            # Auto-classify + include any from codebook rule
            auto_modes = classify_failure(effective_result, tools, arguments, expected_tools, errors)
            codebook_modes = score.get("failure_modes", [])
            all_modes = list(dict.fromkeys(auto_modes + codebook_modes))  # dedupe, preserve order
            row["failure_mode"] = "|".join(all_modes) if all_modes else ""

    # Execution validity placeholder for SQL-generating prompts
    if prompt_id in SQL_GENERATING_PROMPTS:
        if not row.get("execution_valid", "").strip():
            # Check if tool returned an error in the errors column
            if errors and any(t in tools for t in ["Select_Query", "compile_cohort_definition"]):
                row["execution_valid"] = "ERROR"
            else:
                row["execution_valid"] = ""  # will be filled by execution scorer later
    else:
        row["execution_valid"] = "N/A"

    # Always add auto notes
    notes_parts = []
    if row.get("notes", "").strip():
        notes_parts.append(row["notes"].strip())
    if score.get("auto_notes"):
        notes_parts.append(f"[auto] {score['auto_notes']}")
    row["notes"] = " | ".join(notes_parts)

    # Flag for review
    row["_needs_review"] = score.get("needs_review", False)
    row["_auto_result"] = score["result"]

    return row


def score_csv(csv_path: Path, dry_run: bool = False) -> tuple[list[dict], list[dict]]:
    """Score all rows in a CSV file. Returns (scored_rows, flagged_rows)."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return [], []
        original_fields = list(reader.fieldnames)
        rows = list(reader)

    scored = []
    flagged = []

    for row in rows:
        scored_row = score_row(row)
        scored.append(scored_row)

        if scored_row.pop("_needs_review", False):
            flagged_row = {**scored_row, "source_file": str(csv_path)}
            flagged.append(flagged_row)

        scored_row.pop("_auto_result", None)

    if not dry_run:
        # Build fieldnames: original + any new columns
        fieldnames = list(original_fields)
        new_cols = [
            "failure_mode", "execution_valid", "jaccard", "precision", "recall", "f1",
            "provisional_result", "provisional_params", "reviewed", "review_notes",
        ]
        for col in new_cols:
            if col not in fieldnames:
                fieldnames.append(col)
        if "notes" not in fieldnames:
            fieldnames.append("notes")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(scored)

    return scored, flagged


def write_flagged(flagged: list[dict], output_path: Path) -> None:
    """Write flagged-for-review rows to a CSV."""
    if not flagged:
        return

    fieldnames = [
        "source_file", "prompt_id", "category_code", "category_name",
        "prompt", "expected_tools", "result", "tools_called",
        "parameters_correct", "failure_mode", "execution_valid",
        "provisional_result", "provisional_params", "reviewed", "review_notes",
        "text_response", "notes", "model", "provider",
    ]
    actual_fields = set()
    for row in flagged:
        actual_fields.update(row.keys())
    fieldnames = [f for f in fieldnames if f in actual_fields]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flagged)


def generate_summary(all_scored: list[dict]) -> str:
    """Generate a markdown summary of scoring results.

    Rows with provisional scores (needs_review=True, reviewed != "true") are
    excluded from all statistics and a warning is printed.
    """
    # Identify unreviewed provisional rows and exclude from stats
    unreviewed = [
        r for r in all_scored
        if r.get("provisional_result", "").strip()
        and r.get("reviewed", "").strip() != "true"
    ]
    reviewed_count = sum(
        1 for r in all_scored
        if r.get("reviewed", "").strip() == "true"
    )
    rows_for_stats = [r for r in all_scored if r not in unreviewed]

    lines = [
        "# Scoring Summary",
        "",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    if unreviewed:
        lines.extend([
            f"**WARNING: {len(unreviewed)} rows have provisional scores pending human review.**",
            f"Run `uv run python review_flagged.py` to complete review.",
            f"These rows are EXCLUDED from all statistics below.",
            "",
        ])

    if reviewed_count:
        lines.extend([
            f"*Human-reviewed rows: {reviewed_count}*",
            "",
        ])

    # Overall stats
    total = len(rows_for_stats)
    scored = [r for r in rows_for_stats if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
    passes = sum(1 for r in scored if r["result"] == "PASS")
    partials = sum(1 for r in scored if r["result"] == "PARTIAL")
    fails = sum(1 for r in scored if r["result"] == "FAIL")

    lines.extend([
        "## Overall",
        "",
        f"- Total rows: {total}",
        f"- Scored: {len(scored)}",
        f"- PASS: {passes} ({round(passes/len(scored)*100, 1) if scored else 0}%)",
        f"- PARTIAL: {partials} ({round(partials/len(scored)*100, 1) if scored else 0}%)",
        f"- FAIL: {fails} ({round(fails/len(scored)*100, 1) if scored else 0}%)",
        "",
    ])

    # By model (grouped by condition if present)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        cond = r.get("condition", "")
        cond_label = f" [{cond}]" if cond else ""
        mk = f"{r.get('provider', '?')}/{r.get('model', '?')}{cond_label}"
        by_model[mk].append(r)

    lines.extend([
        "## Pass Rate by Model",
        "",
        "| Model | n | PASS | PARTIAL | FAIL | Pass % | Pass+Partial % |",
        "|:------|--:|-----:|--------:|-----:|-------:|---------------:|",
    ])

    for mk in sorted(by_model):
        rows = by_model[mk]
        n = len(rows)
        p = sum(1 for r in rows if r["result"] == "PASS")
        pt = sum(1 for r in rows if r["result"] == "PARTIAL")
        f_count = sum(1 for r in rows if r["result"] == "FAIL")
        pct = round(p / n * 100, 1) if n else 0
        pp_pct = round((p + pt) / n * 100, 1) if n else 0
        lines.append(f"| {mk} | {n} | {p} | {pt} | {f_count} | {pct}% | {pp_pct}% |")

    lines.append("")

    # By category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        cat = r.get("category_code", "?")
        by_cat[cat].append(r)

    cat_names = {
        "C1": "Single Tool Selection",
        "C2": "Tool Disambiguation",
        "C3": "Intra-Server Chaining",
        "C4": "Cross-Server Chaining",
        "C5": "Parameter Construction",
        "C6": "Graceful Degradation",
        "C7": "Multi-Faceted Composition",
        "C8": "Cohort Construction",
    }

    lines.extend([
        "## Pass Rate by Category",
        "",
        "| Category | Name | n | PASS | Pass % |",
        "|:---------|:-----|--:|-----:|-------:|",
    ])

    for cat in sorted(by_cat):
        rows = by_cat[cat]
        n = len(rows)
        p = sum(1 for r in rows if r["result"] == "PASS")
        pct = round(p / n * 100, 1) if n else 0
        name = cat_names.get(cat, cat)
        lines.append(f"| {cat} | {name} | {n} | {p} | {pct}% |")

    lines.append("")

    # By prompt
    by_prompt: dict[int, list[dict]] = defaultdict(list)
    for r in scored:
        pid = int(r.get("prompt_id", 0))
        by_prompt[pid].append(r)

    lines.extend([
        "## Pass Rate by Prompt",
        "",
        "| Prompt | Category | n | PASS | Pass % |",
        "|-------:|:---------|--:|-----:|-------:|",
    ])

    for pid in sorted(by_prompt):
        rows = by_prompt[pid]
        n = len(rows)
        p = sum(1 for r in rows if r["result"] == "PASS")
        pct = round(p / n * 100, 1) if n else 0
        cat = rows[0].get("category_code", "?")
        lines.append(f"| {pid} | {cat} | {n} | {p} | {pct}% |")

    lines.append("")

    # Failure mode distribution
    mode_counts: Counter = Counter()
    for r in scored:
        modes = r.get("failure_mode", "")
        if modes:
            for m in modes.split("|"):
                m = m.strip()
                if m:
                    mode_counts[m] += 1

    if mode_counts:
        lines.extend([
            "## Failure Mode Distribution",
            "",
            "| Mode | Count | Description |",
            "|:-----|------:|:------------|",
        ])
        for mode, count in mode_counts.most_common():
            desc = FAILURE_MODES.get(mode, "")
            lines.append(f"| {mode} | {count} | {desc} |")
        lines.append("")

    # Execution validity (Tier A)
    exec_rows = [r for r in rows_for_stats if r.get("execution_valid") and r["execution_valid"] != "N/A"]
    if exec_rows:
        valid = sum(1 for r in exec_rows if r["execution_valid"] == "VALID")
        invalid = sum(1 for r in exec_rows if r["execution_valid"] == "INVALID")
        error = sum(1 for r in exec_rows if r["execution_valid"] == "ERROR")
        pending = sum(1 for r in exec_rows if r["execution_valid"] == "")
        lines.extend([
            "## Execution Validity (Tier A — SQL-Generating Prompts)",
            "",
            f"- VALID: {valid}",
            f"- INVALID: {invalid}",
            f"- ERROR: {error}",
            f"- Pending: {pending}",
            "",
        ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score OHDSI Agent evaluation results using the codebook.",
    )
    parser.add_argument(
        "--results-dir", default=str(RESULTS_DIR),
        help=f"Directory containing result CSVs (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview scores without writing to files",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory for summary and flagged outputs (default: same as results-dir)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir) if args.output_dir else results_dir.parent

    csv_files = find_result_csvs(results_dir)
    if not csv_files:
        print(f"No result CSVs found in {results_dir}")
        sys.exit(1)

    print(f"Found {len(csv_files)} result CSV files")
    if args.dry_run:
        print("DRY RUN — no files will be modified")
    print()

    all_scored: list[dict] = []
    all_flagged: list[dict] = []

    for csv_path in csv_files:
        print(f"Scoring: {csv_path.relative_to(results_dir)}")
        scored, flagged = score_csv(csv_path, dry_run=args.dry_run)
        all_scored.extend(scored)
        all_flagged.extend(flagged)

        scored_count = sum(1 for r in scored if r.get("result") in ("PASS", "PARTIAL", "FAIL"))
        pass_count = sum(1 for r in scored if r.get("result") == "PASS")
        print(f"  {scored_count} scored, {pass_count} PASS, {len(flagged)} flagged")

    print()
    print(f"Total: {len(all_scored)} rows, {len(all_flagged)} flagged for review")

    # Review status
    provisional = sum(
        1 for r in all_scored
        if r.get("provisional_result", "").strip()
        and r.get("reviewed", "").strip() != "true"
    )
    reviewed = sum(
        1 for r in all_scored
        if r.get("reviewed", "").strip() == "true"
    )
    if provisional or reviewed:
        print(f"Review status: {reviewed} reviewed, {provisional} pending review")
        if provisional:
            print(f"  Run `uv run python review_flagged.py` to review provisional scores")

    # Write flagged
    flagged_path = output_dir / "flagged_for_review.csv"
    if all_flagged and not args.dry_run:
        write_flagged(all_flagged, flagged_path)
        print(f"Flagged rows written to: {flagged_path}")

    # Write summary
    summary = generate_summary(all_scored)
    summary_path = output_dir / "scoring_summary.md"
    if not args.dry_run:
        summary_path.write_text(summary, encoding="utf-8")
        print(f"Summary written to: {summary_path}")
    else:
        print()
        print(summary)


if __name__ == "__main__":
    main()
