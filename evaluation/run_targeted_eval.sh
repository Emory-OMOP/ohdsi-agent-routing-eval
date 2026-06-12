#!/bin/bash
# Run deepseek targeted evaluation for builder-spec discoverability prompts.
#
# Path A (phenotype_id): P15, P16, P17, P18, P22
# Path B (build+execute): P31, P32, P33
#
# Guided condition only — forces CIRCE pipeline, verifies tool capability.
#
# Usage:
#   bash run_targeted_eval.sh [--label LABEL]
#
#   --label: tag for the output file (default: "targeted")
#
# Output goes to results/deepseek/deepseek_chat/temp_0.0/guided/ via the
# existing harness, plus a log to /tmp/claude/ for quick inspection.

set -euo pipefail

LABEL="targeted"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="/tmp/claude/deepseek-${LABEL}-eval-output.txt"
mkdir -p /tmp/claude

cd "$SCRIPT_DIR"

PROMPTS="15,16,17,18,22,31,32,33"

{
  echo "=== deepseek targeted eval (label: $LABEL) ==="
  echo "Prompts: $PROMPTS"
  echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo ""

  uv run python run_evaluation.py \
    --provider deepseek \
    --model deepseek-chat \
    --temperature 0.0 \
    --condition guided \
    --prompts "$PROMPTS" \
    --runs 1 \
    --delay 3 2>&1

  echo ""
  echo "Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "$OUTPUT"

echo ""
echo "Results written to: $OUTPUT"
