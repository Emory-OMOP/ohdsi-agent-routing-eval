"""Fix P25 overrides: set parameters_correct=N/A for all reviewed P25 rows.

Scans active (non-archive) result CSVs, finds P25 rows where reviewed=true,
and sets parameters_correct to N/A.

Usage:
    uv run python fix_p25_params.py          # dry run (preview)
    uv run python fix_p25_params.py --apply   # actually write changes
"""

import csv
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)

RESULTS_DIR = Path(__file__).parent / "results"
SKIP_FILES = {"result_provenance.csv", "flagged_for_review.csv"}


def find_csvs(results_dir: Path) -> list[Path]:
    """Find active result CSVs (skip archive)."""
    csvs = []
    for p in sorted(results_dir.rglob("*.csv")):
        if p.name in SKIP_FILES or p.name.startswith("."):
            continue
        # Skip archive directory
        if "archive" in p.parts:
            continue
        csvs.append(p)
    return csvs


def main():
    apply = "--apply" in sys.argv

    if not apply:
        print("DRY RUN — pass --apply to write changes\n")

    csvs = find_csvs(RESULTS_DIR)
    total_fixed = 0

    for csv_path in csvs:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames)
            rows = list(reader)

        changed = False
        for row in rows:
            if row.get("prompt_id") != "25":
                continue
            if row.get("reviewed", "").strip() != "true":
                continue
            old_val = row.get("parameters_correct", "")
            if old_val == "N/A":
                continue

            print(f"{csv_path.relative_to(RESULTS_DIR)}")
            print(f"  P25 | reviewed=true | parameters_correct: {old_val!r} -> 'N/A'")
            row["parameters_correct"] = "N/A"
            changed = True
            total_fixed += 1

        if changed and apply:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

    print(f"\n{'Fixed' if apply else 'Would fix'}: {total_fixed} rows")


if __name__ == "__main__":
    main()
