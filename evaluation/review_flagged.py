"""Interactive CLI for reviewing provisionally-scored evaluation rows.

Scans result CSVs for rows with a provisional_result but no final result
(reviewed != "true"), presents them one at a time, and writes approvals
back to the source CSV immediately.

Usage:
    uv run python review_flagged.py              # interactive review
    uv run python review_flagged.py --status     # show pending/reviewed counts
    uv run python review_flagged.py --dry-run    # preview without writing
    uv run python review_flagged.py --prompt 25  # filter to prompt_id 25
    uv run python review_flagged.py --model claude-sonnet-4-20250514  # filter to model
"""

from __future__ import annotations

import argparse
import csv
import signal
import sys
import textwrap
from pathlib import Path

csv.field_size_limit(10_000_000)

RESULTS_DIR = Path(__file__).parent / "results"

# ── Graceful shutdown ─────────────────────────────────────────────────────

_shutdown_requested = False


def _handle_sigint(signum, frame):
    """Set shutdown flag on first Ctrl+C; force-exit on second."""
    global _shutdown_requested
    if _shutdown_requested:
        print("\n  Second interrupt — exiting immediately.")
        sys.exit(1)
    _shutdown_requested = True
    print("\n  Ctrl+C received — will stop after current row. Press again to force-exit.")


signal.signal(signal.SIGINT, _handle_sigint)


# ── CSV helpers ───────────────────────────────────────────────────────────

def find_result_csvs(results_dir: Path) -> list[Path]:
    """Find all result CSV files (recursive, skip provenance and flagged)."""
    skip = {"result_provenance.csv", "flagged_for_review.csv"}
    csvs = []
    for p in sorted(results_dir.rglob("*.csv")):
        if p.name in skip or p.name.startswith("."):
            continue
        csvs.append(p)
    return csvs


def load_csv(csv_path: Path) -> tuple[list[str], list[dict]]:
    """Load a CSV, returning (fieldnames, rows)."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_csv(csv_path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write rows back to a CSV."""
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ── Review item collection ────────────────────────────────────────────────

class ReviewItem:
    """A single row needing review, with its CSV context for write-back."""

    def __init__(self, csv_path: Path, fieldnames: list[str],
                 row: dict, row_index: int):
        self.csv_path = csv_path
        self.fieldnames = fieldnames
        self.row = row
        self.row_index = row_index

    @property
    def prompt_id(self) -> str:
        return self.row.get("prompt_id", "?")

    @property
    def model(self) -> str:
        return self.row.get("model", "?")

    @property
    def provider(self) -> str:
        return self.row.get("provider", "?")

    @property
    def condition(self) -> str:
        return self.row.get("condition", "")


def collect_unreviewed(results_dir: Path, prompt_filter: int | None = None,
                       model_filter: str | None = None) -> list[ReviewItem]:
    """Scan all CSVs for rows with provisional scores pending review."""
    items: list[ReviewItem] = []

    for csv_path in find_result_csvs(results_dir):
        fieldnames, rows = load_csv(csv_path)

        for idx, row in enumerate(rows):
            # Must have a provisional result and not yet reviewed
            if not row.get("provisional_result", "").strip():
                continue
            if row.get("reviewed", "").strip() == "true":
                continue

            # Apply filters
            if prompt_filter is not None:
                try:
                    if int(row.get("prompt_id", 0)) != prompt_filter:
                        continue
                except (ValueError, TypeError):
                    continue

            if model_filter is not None:
                if model_filter.lower() not in row.get("model", "").lower():
                    continue

            items.append(ReviewItem(csv_path, fieldnames, row, idx))

    return items


def count_review_status(results_dir: Path) -> tuple[int, int, int]:
    """Count (total_flagged, reviewed, pending) across all CSVs."""
    reviewed = 0
    pending = 0

    for csv_path in find_result_csvs(results_dir):
        _, rows = load_csv(csv_path)
        for row in rows:
            has_provisional = bool(row.get("provisional_result", "").strip())
            is_reviewed = row.get("reviewed", "").strip() == "true"

            if has_provisional and is_reviewed:
                reviewed += 1
            elif has_provisional:
                pending += 1

    return reviewed + pending, reviewed, pending


# ── Display ───────────────────────────────────────────────────────────────

def display_item(item: ReviewItem, index: int, total: int) -> None:
    """Display a review item for human evaluation."""
    row = item.row
    print()
    print("=" * 72)
    print(f"  Review {index + 1}/{total}")
    print("=" * 72)
    print()

    # Identity
    pid = row.get("prompt_id", "?")
    cat = row.get("category_code", "?")
    cat_name = row.get("category_name", "")
    cond = row.get("condition", "")
    print(f"  Prompt:    P{pid} ({cat}: {cat_name})")
    print(f"  Model:     {row.get('provider', '?')}/{row.get('model', '?')}")
    if cond:
        print(f"  Condition: {cond}")
    print(f"  Source:    {item.csv_path.name}")
    print()

    # Prompt text
    prompt_text = row.get("prompt", "")
    if prompt_text:
        print("  PROMPT:")
        for line in textwrap.wrap(prompt_text, width=68):
            print(f"    {line}")
        print()

    # Expected tools
    expected = row.get("expected_tools", "")
    if expected:
        print(f"  Expected:  {expected}")

    # Actual tools
    tools = row.get("tools_called", "")
    if tools:
        print(f"  Called:     {tools}")
    print()

    # Text response (the key thing being reviewed)
    text_resp = row.get("text_response", "")
    if text_resp:
        print("  TEXT RESPONSE:")
        print("  " + "-" * 68)
        # Truncate very long responses
        display_text = text_resp[:2000]
        if len(text_resp) > 2000:
            display_text += f"\n... [{len(text_resp) - 2000} more chars]"
        for line in display_text.split("\n"):
            print(f"    {line}")
        print("  " + "-" * 68)
        print()

    # Auto-scorer notes (what to verify)
    notes = row.get("notes", "")
    if notes:
        print(f"  Notes:     {notes}")
        print()

    # Provisional score
    prov_result = row.get("provisional_result", "")
    prov_params = row.get("provisional_params", "")
    print(f"  Provisional: result={prov_result}, params={prov_params}")

    # Existing review notes (from prior partial review)
    existing_notes = row.get("review_notes", "")
    if existing_notes:
        print(f"  Prior notes: {existing_notes}")
    print()


# ── Interactive actions ───────────────────────────────────────────────────

def approve_item(item: ReviewItem, review_notes: str = "") -> None:
    """Approve: copy provisional score to final, mark reviewed."""
    item.row["result"] = item.row.get("provisional_result", "")
    item.row["parameters_correct"] = item.row.get("provisional_params", "")
    item.row["reviewed"] = "true"
    if review_notes:
        item.row["review_notes"] = review_notes
    _write_back(item)


def override_item(item: ReviewItem, new_result: str, new_params: str,
                  review_notes: str = "") -> None:
    """Override: set custom score, mark reviewed."""
    item.row["result"] = new_result
    item.row["parameters_correct"] = new_params
    item.row["reviewed"] = "true"
    if review_notes:
        item.row["review_notes"] = review_notes
    _write_back(item)


def _write_back(item: ReviewItem) -> None:
    """Write the updated row back to its source CSV."""
    fieldnames, rows = load_csv(item.csv_path)
    rows[item.row_index] = item.row

    # Ensure new columns are in fieldnames
    for col in ("provisional_result", "provisional_params", "reviewed", "review_notes"):
        if col not in fieldnames:
            fieldnames.append(col)

    write_csv(item.csv_path, fieldnames, rows)


def prompt_override() -> tuple[str, str] | None:
    """Ask user for override values. Returns (result, params) or None to cancel."""
    valid_results = ("PASS", "PARTIAL", "FAIL")
    valid_params = ("CORRECT", "PARTIAL", "INCORRECT", "N/A")

    print(f"  Result options: {', '.join(valid_results)}")
    result = input("  Result > ").strip().upper()
    if result not in valid_results:
        print(f"  Invalid result: {result}")
        return None

    print(f"  Params options: {', '.join(valid_params)}")
    params = input("  Params > ").strip().upper()
    if params not in valid_params:
        print(f"  Invalid params: {params}")
        return None

    return result, params


def prompt_review_notes() -> str:
    """Ask for optional qualitative notes. Enter to skip."""
    notes = input("  Notes (optional, Enter to skip) > ").strip()
    return notes


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive review of provisionally-scored evaluation rows.",
    )
    parser.add_argument(
        "--results-dir", default=str(RESULTS_DIR),
        help=f"Directory containing result CSVs (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--prompt", type=int, default=None,
        help="Filter to a specific prompt_id",
    )
    parser.add_argument(
        "--model", default=None,
        help="Filter to a specific model (substring match)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show flagged rows without writing changes",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print review status summary and exit",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    # --status: just print counts and exit
    if args.status:
        total, reviewed, pending = count_review_status(results_dir)
        print(f"Review status ({results_dir}):")
        print(f"  Total flagged:  {total}")
        print(f"  Reviewed:       {reviewed}")
        print(f"  Pending:        {pending}")
        if pending:
            print(f"\nRun `uv run python review_flagged.py` to review pending rows.")
        else:
            print(f"\nAll flagged rows have been reviewed.")
        return

    # Collect unreviewed items
    items = collect_unreviewed(results_dir, args.prompt, args.model)

    if not items:
        print("No unreviewed provisional rows found.")
        total, reviewed, _ = count_review_status(results_dir)
        if reviewed:
            print(f"  ({reviewed} rows already reviewed)")
        return

    print(f"Found {len(items)} rows pending review")
    if args.dry_run:
        print("DRY RUN — no files will be modified")
    print()
    print("Actions: [a]pprove  [o]verride  [s]kip  [q]uit")

    approved = 0
    overridden = 0
    skipped = 0

    for i, item in enumerate(items):
        if _shutdown_requested:
            print(f"\nShutdown requested. {approved + overridden} saved, {skipped} skipped.")
            break

        display_item(item, i, len(items))

        while True:
            try:
                action = input("  Action [a/o/s/q] > ").strip().lower()
            except EOFError:
                action = "q"

            if action in ("a", "approve"):
                notes = "" if args.dry_run else prompt_review_notes()
                if args.dry_run:
                    print("  [dry-run] Would approve")
                else:
                    approve_item(item, review_notes=notes)
                    print("  Approved ✓")
                approved += 1
                break

            elif action in ("o", "override"):
                override = prompt_override()
                if override is None:
                    print("  Override cancelled, try again.")
                    continue
                new_result, new_params = override
                notes = "" if args.dry_run else prompt_review_notes()
                if args.dry_run:
                    print(f"  [dry-run] Would override to {new_result}/{new_params}")
                else:
                    override_item(item, new_result, new_params, review_notes=notes)
                    print(f"  Overridden to {new_result}/{new_params} ✓")
                overridden += 1
                break

            elif action in ("s", "skip"):
                skipped += 1
                print("  Skipped")
                break

            elif action in ("q", "quit"):
                print(f"\nQuitting. {approved + overridden} saved, {skipped} skipped, "
                      f"{len(items) - i} remaining.")
                return

            else:
                print("  Invalid action. Use [a]pprove, [o]verride, [s]kip, or [q]uit.")

    # Final summary
    print()
    print(f"Review complete: {approved} approved, {overridden} overridden, {skipped} skipped")
    remaining = len(items) - approved - overridden - skipped
    if remaining > 0:
        print(f"  {remaining} rows still pending (interrupted)")


if __name__ == "__main__":
    main()
