#!/bin/bash
# Full evaluation matrix runner for JAMIA publication.
#
# Primary: 6 models × 4 temps × 10 runs × 2 conditions = 9,120 evals
# Satellite: qwen3:14b × 4 temps × 3 runs × 2 conditions = 456 evals
# Grand total: 9,576 evaluations
#
# Sequential execution — one model/temp/condition at a time for clean
# interpretability and no MCP server contention.
#
# All output is logged to results/matrix_run.log (tee'd to terminal).
# Progress is tracked in results/matrix_progress.log with one line per
# completed model/temp/condition cell — check this to see where a
# resumed run will pick up.
#
# Usage:
#   bash run_full_matrix.sh              # run everything
#   bash run_full_matrix.sh --dry-run    # print commands without executing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN — commands will be printed but not executed ==="
    echo ""
fi

TEMPS=(0.0 0.3 0.7 1.0)
CONDITIONS=(open guided)
DELAY=2

# ── Log setup ────────────────────────────────────────────────────────────

RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"
FULL_LOG="$RESULTS_DIR/matrix_run.log"
PROGRESS_LOG="$RESULTS_DIR/matrix_progress.log"
FAILED_LOG="$RESULTS_DIR/failed_runs.log"

# Tee all output to the full log (append mode)
exec > >(tee -a "$FULL_LOG") 2>&1

# ── Primary matrix: 6 models × 10 runs ──────────────────────────────────

PRIMARY_RUNS=10
declare -a PRIMARY_MODELS=(
    "claude:claude-sonnet-4-20250514"
    "openai:gpt-4.1"
    "claude:claude-haiku-4-5-20251001"
    "openai:gpt-4.1-mini"
    "ollama:qwen3:8b"
    "ollama:llama3.1:8b"
)

# ── Satellite: qwen3:14b × 3 runs ───────────────────────────────────────

SATELLITE_RUNS=3
declare -a SATELLITE_MODELS=(
    "ollama:qwen3:14b"
)

# ── Progress tracking ────────────────────────────────────────────────────

is_cell_done() {
    # Check if a model/temp/condition cell is already logged as complete
    local key="$1"
    if [[ -f "$PROGRESS_LOG" ]] && grep -qF "$key" "$PROGRESS_LOG"; then
        return 0
    fi
    return 1
}

# ── Runner ───────────────────────────────────────────────────────────────

run_model() {
    local provider_model="$1"
    local runs="$2"
    local provider="${provider_model%%:*}"
    local model="${provider_model#*:}"

    for temp in "${TEMPS[@]}"; do
        for condition in "${CONDITIONS[@]}"; do
            local cell_key="$provider/$model/temp_$temp/$condition"

            # Skip cells already completed in a previous matrix run
            if ! $DRY_RUN && is_cell_done "$cell_key"; then
                echo "  SKIP (already done): $cell_key"
                continue
            fi

            echo "────────────────────────────────────────────────────────"
            echo "  Provider:  $provider"
            echo "  Model:     $model"
            echo "  Temp:      $temp"
            echo "  Condition: $condition"
            echo "  Runs:      $runs"
            echo "  Started:   $(date)"
            echo "────────────────────────────────────────────────────────"

            CMD=(
                uv run --with httpx python run_evaluation.py
                --provider "$provider"
                --model "$model"
                --temperature "$temp"
                --condition "$condition"
                --runs "$runs"
                --resume
                --delay "$DELAY"
            )

            if $DRY_RUN; then
                echo "  ${CMD[*]}"
                echo ""
            else
                if "${CMD[@]}"; then
                    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) DONE $cell_key" >> "$PROGRESS_LOG"
                    echo ""
                else
                    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) FAILED $cell_key" >> "$FAILED_LOG"
                    echo "  *** FAILED: $cell_key (exit $?)"
                    echo ""
                fi
            fi
        done
    done
}

# ── Execution ────────────────────────────────────────────────────────────

TOTAL_START=$(date +%s)

echo "============================================================"
echo "  JAMIA Evaluation Matrix"
echo "  Started: $(date)"
echo "  Primary: ${#PRIMARY_MODELS[@]} models × ${#TEMPS[@]} temps × $PRIMARY_RUNS runs × ${#CONDITIONS[@]} conditions"
echo "  Satellite: ${#SATELLITE_MODELS[@]} models × ${#TEMPS[@]} temps × $SATELLITE_RUNS runs × ${#CONDITIONS[@]} conditions"
echo "  Full log: $FULL_LOG"
echo "  Progress: $PROGRESS_LOG"
echo "============================================================"
echo ""

if [[ -f "$PROGRESS_LOG" ]]; then
    DONE_COUNT=$(wc -l < "$PROGRESS_LOG" | tr -d ' ')
    echo "  Resuming — $DONE_COUNT cells previously completed"
    echo ""
fi

echo "=== PRIMARY MODELS (10 runs) ==="
echo ""
for pm in "${PRIMARY_MODELS[@]}"; do
    run_model "$pm" "$PRIMARY_RUNS"
done

echo "=== SATELLITE MODELS (3 runs) ==="
echo ""
for sm in "${SATELLITE_MODELS[@]}"; do
    run_model "$sm" "$SATELLITE_RUNS"
done

TOTAL_END=$(date +%s)
ELAPSED=$(( TOTAL_END - TOTAL_START ))
HOURS=$(( ELAPSED / 3600 ))
MINS=$(( (ELAPSED % 3600) / 60 ))

echo "============================================================"
echo "  Matrix complete"
echo "  Finished: $(date)"
echo "  Elapsed: ${HOURS}h ${MINS}m"
echo "  Results: $RESULTS_DIR/"
echo "  Provenance: $RESULTS_DIR/result_provenance.csv"
echo "  Progress: $PROGRESS_LOG"
if [[ -f "$FAILED_LOG" ]]; then
    FAIL_COUNT=$(wc -l < "$FAILED_LOG" | tr -d ' ')
    echo "  Failed cells: $FAIL_COUNT (see $FAILED_LOG)"
fi
echo "============================================================"
