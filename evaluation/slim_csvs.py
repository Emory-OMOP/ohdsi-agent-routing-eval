"""One-time migration: slim result CSVs by dropping tool_results and compacting tool_arguments.

Usage:
    uv run python slim_csvs.py [--dry-run]

Changes per CSV:
  - Drops the `tool_results` column entirely (large tool output blobs)
  - Compacts `tool_arguments`: replaces `spec_json` values with `true`
    (scoring only checks existence, never reads content)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)

RESULTS_DIR = Path(__file__).parent / "results"


def compact_tool_arguments(raw: str) -> str:
    """Compact tool_arguments JSON: replace spec_json values with true."""
    if not raw or raw.strip() == "":
        return raw
    try:
        args_list = json.loads(raw)
        if not isinstance(args_list, list):
            return raw
        for args in args_list:
            if isinstance(args, dict) and "spec_json" in args:
                args["spec_json"] = True
        return json.dumps(args_list, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return raw


def slim_csv(csv_path: Path, dry_run: bool = False) -> dict:
    """Slim a single CSV file. Returns stats dict."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    had_tool_results = "tool_results" in fieldnames
    had_tool_arguments = "tool_arguments" in fieldnames

    original_size = csv_path.stat().st_size

    # Drop tool_results from fieldnames
    new_fieldnames = [f for f in fieldnames if f != "tool_results"]

    # Process rows
    for row in rows:
        row.pop("tool_results", None)
        if had_tool_arguments:
            row["tool_arguments"] = compact_tool_arguments(row.get("tool_arguments", ""))

    if not dry_run:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=new_fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    new_size = csv_path.stat().st_size if not dry_run else None
    return {
        "path": csv_path,
        "rows": len(rows),
        "had_tool_results": had_tool_results,
        "had_tool_arguments": had_tool_arguments,
        "original_size": original_size,
        "new_size": new_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Slim result CSVs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    csvs = sorted(RESULTS_DIR.rglob("*.csv"))
    # Exclude non-result files
    csvs = [c for c in csvs if c.name != "result_provenance.csv"]

    if not csvs:
        print("No result CSVs found")
        sys.exit(1)

    print(f"Found {len(csvs)} result CSVs")
    if args.dry_run:
        print("[DRY RUN]")
    print()

    total_original = 0
    total_new = 0

    for csv_path in csvs:
        stats = slim_csv(csv_path, dry_run=args.dry_run)
        rel = csv_path.relative_to(RESULTS_DIR)
        total_original += stats["original_size"]

        if args.dry_run:
            dropped = "drop tool_results" if stats["had_tool_results"] else "no tool_results"
            compact = "compact tool_arguments" if stats["had_tool_arguments"] else "no tool_arguments"
            print(f"  {rel}: {stats['rows']} rows, {dropped}, {compact} ({stats['original_size']:,} bytes)")
        else:
            saved = stats["original_size"] - stats["new_size"]
            total_new += stats["new_size"]
            pct = (saved / stats["original_size"] * 100) if stats["original_size"] > 0 else 0
            print(f"  {rel}: {stats['original_size']:,} → {stats['new_size']:,} bytes ({pct:.0f}% reduction)")

    print()
    if not args.dry_run:
        saved = total_original - total_new
        pct = (saved / total_original * 100) if total_original > 0 else 0
        print(f"Total: {total_original:,} → {total_new:,} bytes ({saved:,} saved, {pct:.0f}% reduction)")
    else:
        print(f"Total original size: {total_original:,} bytes")


if __name__ == "__main__":
    main()
