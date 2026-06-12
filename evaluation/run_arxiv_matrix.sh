#!/bin/bash
# ArXiv evaluation matrix runner.
#
# Scope: 4 models × 1 temp × 2 conditions × 5 runs = 1,320 prompt executions
#
# Design: 2×2 balanced (cloud/local × frontier/small)
#   Cloud (Anthropic):  claude-sonnet-4-20250514, claude-haiku-4-5-20251001
#   Local (Ollama):     qwen3:14b, qwen3:8b
#
# Temperature fixed at 0.0 (deterministic baseline).
# Temperature as a continuous variable is deferred to JAMIA.
#
# Usage:
#   Provide provider API keys via environment variables (see repository README),
#   then run:  bash run_arxiv_matrix.sh   (add --dry-run to print without executing)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Disable omop-sidecar MCP server — not under test in this evaluation.
export MCP_SIDECAR_URL=""

REPO="$(cd "$SCRIPT_DIR/.." && pwd)"  # repo root (evaluation/ sits at the top level)
OMCP_REPO="${OMCP_REPO:-$REPO/servers/omcp}"  # vendored omcp server (see servers/omcp/VENDORED.md)
DUCKDB_PATH="${DUCKDB_PATH:-$REPO/synthea_omop_etl.duckdb}"  # override via env; see README for obtaining the DB

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN — commands will be printed but not executed ==="
    echo ""
fi

# ── Restart all servers ──────────────────────────────────────────────
# All MCP servers + webapp must be restarted to pick up code changes
# and MCP_SIDECAR_URL="".

PIDS=()

kill_port() {
    local port="$1"
    local pid
    pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        echo "  Killing port $port (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        for i in {1..10}; do
            if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then return 0; fi
            sleep 1
        done
    fi
}

wait_for_port() {
    local port="$1" name="$2"
    for i in {1..30}; do
        if lsof -ti:"$port" > /dev/null 2>&1; then
            echo "  $name ready (port $port)"
            return 0
        fi
        sleep 1
    done
    echo "  WARNING: $name not ready after 30s (port $port)"
    return 1
}

restart_all_servers() {
    echo "Stopping existing servers..."
    kill_port 8000  # webapp
    kill_port 8001  # ohdsi-vocab
    kill_port 8002  # circe-compiler
    kill_port 8003  # omcp

    echo ""
    echo "Starting MCP servers..."

    # ohdsi-vocab (port 8001)
    cd "$REPO/servers/ohdsi-vocab"
    uv sync --quiet
    OHDSI_DUCKDB_PATH="$DUCKDB_PATH" \
    OHDSI_VOCAB_SCHEMA="main_vocab" \
    OHDSI_CDM_SCHEMA="main_cdm" \
    MCP_TRANSPORT=streamable-http \
    MCP_PORT=8001 \
    uv run python server.py &
    PIDS+=($!)
    echo "  ohdsi-vocab:    PID $! → :8001"

    # circe-compiler (port 8002)
    cd "$REPO/servers/circe-compiler"
    uv sync --quiet
    OHDSI_DUCKDB_PATH="$DUCKDB_PATH" \
    MCP_TRANSPORT=streamable-http \
    MCP_PORT=8002 \
    OMCP_URL=http://localhost:8003/sse \
    uv run python -m circe_compiler &
    PIDS+=($!)
    echo "  circe-compiler: PID $! → :8002"

    # omcp (port 8003, streamable-http — requires mcp>=1.26.0)
    cd "$OMCP_REPO"
    DB_TYPE=duckdb \
    DB_PATH="$DUCKDB_PATH" \
    DB_READ_ONLY=true \
    CDM_SCHEMA=main_cdm \
    VOCAB_SCHEMA=main_vocab \
    ENABLE_LANGFUSE=false \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=localhost \
    MCP_PORT=8003 \
    FASTMCP_PORT=8003 \
    FASTMCP_HOST=localhost \
    uv run omcp &
    PIDS+=($!)
    echo "  omcp:           PID $! → :8003"

    echo ""
    echo "Waiting for MCP servers..."
    wait_for_port 8001 "ohdsi-vocab"
    wait_for_port 8002 "circe-compiler"
    wait_for_port 8003 "omcp"

    # webapp (port 8000) — starts after MCP servers are ready
    echo ""
    echo "Starting webapp (sidecar disabled)..."
    cd "$REPO/webapp"
    # Langfuse is part of the full stack. Keys come from the environment / .env
    # (no inline defaults — set LANGFUSE_PUBLIC_KEY/SECRET_KEY to the project keys
    # created by the Langfuse stack in langfuse/). For a lean run without Langfuse,
    # set LANGFUSE_ENABLED=false (see README "Run without Langfuse").
    MCP_SIDECAR_URL="" \
    BETA_PASSKEY="${BETA_PASSKEY:-changeme}" \
    LANGFUSE_ENABLED="${LANGFUSE_ENABLED:-true}" \
    LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}" \
    LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}" \
    LANGFUSE_HOST="${LANGFUSE_HOST:-http://localhost:3000}" \
    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
    PIDS+=($!)
    echo "  webapp:         PID $! → :8000"

    wait_for_port 8000 "webapp"
    if ! curl -sf "http://localhost:8000/api/health" >/dev/null 2>&1; then
        echo "  ERROR: Backend health check failed"
        exit 1
    fi

    cd "$SCRIPT_DIR"
}

cleanup() {
    echo ""
    echo "Stopping all servers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "All servers stopped."
}
trap cleanup EXIT INT TERM

if ! $DRY_RUN; then
    restart_all_servers
else
    echo "  Would restart all servers (ohdsi-vocab, circe-compiler, omcp, webapp)"
    echo ""
fi

TEMP=0.0
CONDITIONS=(open guided)
RUNS=5
DELAY=2

declare -a MODELS=(
    "claude:claude-sonnet-4-20250514"
    "claude:claude-haiku-4-5-20251001"
    "ollama:qwen3:14b"
    "ollama:qwen3:8b"
)

# ── Log setup ────────────────────────────────────────────────────────────

RESULTS_DIR="$SCRIPT_DIR/results"
mkdir -p "$RESULTS_DIR"
FULL_LOG="$RESULTS_DIR/arxiv_matrix_run.log"
PROGRESS_LOG="$RESULTS_DIR/arxiv_matrix_progress.log"
FAILED_LOG="$RESULTS_DIR/arxiv_failed_runs.log"

exec > >(tee -a "$FULL_LOG") 2>&1

# ── Progress tracking ────────────────────────────────────────────────────

is_cell_done() {
    local key="$1"
    if [[ -f "$PROGRESS_LOG" ]] && grep -qF "$key" "$PROGRESS_LOG"; then
        return 0
    fi
    return 1
}

# ── Runner ───────────────────────────────────────────────────────────────

run_model() {
    local provider_model="$1"
    local provider="${provider_model%%:*}"
    local model="${provider_model#*:}"

    for condition in "${CONDITIONS[@]}"; do
        local cell_key="$provider/$model/temp_$TEMP/$condition"

        if ! $DRY_RUN && is_cell_done "$cell_key"; then
            echo "  SKIP (already done): $cell_key"
            continue
        fi

        echo "────────────────────────────────────────────────────────"
        echo "  Provider:  $provider"
        echo "  Model:     $model"
        echo "  Temp:      $TEMP"
        echo "  Condition: $condition"
        echo "  Runs:      $RUNS"
        echo "  Started:   $(date)"
        echo "────────────────────────────────────────────────────────"

        CMD=(
            uv run --with httpx python run_evaluation.py
            --provider "$provider"
            --model "$model"
            --temperature "$TEMP"
            --condition "$condition"
            --runs "$RUNS"
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
}

# ── Execution ────────────────────────────────────────────────────────────

TOTAL_START=$(date +%s)

echo "============================================================"
echo "  ArXiv Evaluation Matrix"
echo "  Started: $(date)"
echo "  Models: ${#MODELS[@]} × temp=$TEMP × ${#CONDITIONS[@]} conditions × $RUNS runs"
echo "  Total cells: $(( ${#MODELS[@]} * ${#CONDITIONS[@]} ))"
echo "  Total prompt executions: $(( ${#MODELS[@]} * ${#CONDITIONS[@]} * $RUNS * 33 ))"
echo "  Full log: $FULL_LOG"
echo "  Progress: $PROGRESS_LOG"
echo "============================================================"
echo ""

if [[ -f "$PROGRESS_LOG" ]]; then
    DONE_COUNT=$(wc -l < "$PROGRESS_LOG" | tr -d ' ')
    echo "  Resuming — $DONE_COUNT cells previously completed"
    echo ""
fi

for pm in "${MODELS[@]}"; do
    run_model "$pm"
done

TOTAL_END=$(date +%s)
ELAPSED=$(( TOTAL_END - TOTAL_START ))
HOURS=$(( ELAPSED / 3600 ))
MINS=$(( (ELAPSED % 3600) / 60 ))

echo "============================================================"
echo "  ArXiv matrix complete"
echo "  Finished: $(date)"
echo "  Elapsed: ${HOURS}h ${MINS}m"
echo "  Results: $RESULTS_DIR/"
echo "  Progress: $PROGRESS_LOG"
if [[ -f "$FAILED_LOG" ]]; then
    FAIL_COUNT=$(wc -l < "$FAILED_LOG" | tr -d ' ')
    echo "  Failed cells: $FAIL_COUNT (see $FAILED_LOG)"
fi
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Score:   uv run python score_results.py"
echo "  2. Review:  uv run python review_flagged.py"
echo "  3. Tier B:  uv run python gold_standards.py score-all --db ../synthea_omop_etl.duckdb"
echo "  4. Analyze: uv run python analyze_results.py"
