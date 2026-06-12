# JAMIA Evaluation Harness

**Multi-model tool routing evaluation for the OHDSI Agent MCP architecture.**

Sends natural-language prompts to the OHDSI Agent webapp, records which MCP tools each model selects and how it parameterizes them, then scores correctness against a deterministic codebook. Designed for the two-condition experiment comparing open tool access vs structured cohort-building paths.

## Evaluation Design

### Two-condition experiment

| Condition | Tools available | Prompts | Purpose |
|-----------|----------------|---------|---------|
| **Open** | All 20 (including Select_Query, Get_Information_Schema) | All 33 | Naturalistic routing — models choose freely |
| **Guided** | 18 (Select_Query and Get_Information_Schema hidden) | P19, P21, P31-P33 | Forces structured tool paths via `build_cohort_definition` |

**Hypothesis**: `build_cohort_definition` compensates for smaller model capability — models that write bad SQL via Select_Query may produce correct cohorts through the structured builder.

### Model roster

| Tier | Provider | Model | Rationale |
|------|----------|-------|-----------|
| Frontier | claude | claude-sonnet-4-20250514 | Anthropic flagship |
| Frontier | openai | gpt-4o | OpenAI flagship |
| Mid | claude | claude-haiku-4-5-20251001 | Distilled Anthropic |
| Mid | openai | gpt-4o-mini | Distilled OpenAI |
| Small | ollama | qwen3:8b | Open-weight, local |
| Small | ollama | llama3.1:8b | Open-weight, local |

**Satellite** (supplementary data): `qwen3:14b` via ollama, 3 runs per cell.

Within-tier comparison gives Anthropic vs OpenAI at two capability levels. Cross-tier gives two independent scaling curves (Sonnet→Haiku, GPT-4o→4o-mini).

### Temperature levels

| Value | Purpose |
|-------|---------|
| 0.0 | Deterministic baseline |
| 0.3 | Near-deterministic variance |
| 0.7 | Balanced exploration |
| 1.0 | Maximum stochasticity |

### Matrix totals

| | Models | Prompts | Temps | Runs | Evals |
|---|---|---|---|---|---|
| Primary open | 6 | 33 | 4 | 10 | 7,920 |
| Primary guided | 6 | 5 | 4 | 10 | 1,200 |
| Satellite open | 1 | 33 | 4 | 3 | 396 |
| Satellite guided | 1 | 5 | 4 | 3 | 60 |
| **Total** | | | | | **9,576** |

## Quick Start

### Prerequisites

1. **Webapp running** at `http://localhost:8000` with all 3 MCP servers:
   - ohdsi-vocab (`:8001`), circe-compiler (`:8002`), omcp (`:8003`)
2. **Ollama running** with `qwen3:8b` and `llama3.1:8b` pulled
3. **API keys** set: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (in webapp env)
4. **`allow_raw_sql: True`** in `webapp/backend/config.py`

### Smoke test

```bash
cd publications/jamia/plan_and_results

# Single prompt, one condition
uv run python run_evaluation.py \
    --provider ollama --model qwen3:8b --prompts 19 --condition open

# Both conditions
uv run python run_evaluation.py \
    --provider ollama --model qwen3:8b --prompts 19 --condition guided
```

## Running the Full Matrix

```bash
# Preview all commands without executing
bash run_full_matrix.sh --dry-run

# Run everything (resumable — safe to restart)
bash run_full_matrix.sh
```

The matrix runner iterates: for each model → for each temperature → for each condition. Sequential execution prevents MCP server contention.

### Harness CLI reference

```
uv run python run_evaluation.py \
    --provider {ollama,claude,openai,gemini,deepseek} \
    --model MODEL_NAME \
    --condition {open,guided}     # default: open
    --temperature FLOAT           # default: provider default
    --runs N                      # default: 1
    --resume                      # skip completed prompts
    --prompts 19,21,31            # subset; default: all (or guided subset)
    --delay SECONDS               # between prompts; default: 2
    --base-url URL                # default: http://localhost:8000
```

## Stopping and Resuming

### Graceful shutdown (Ctrl+C)

The harness handles interrupts gracefully:

- **First Ctrl+C** — the in-flight prompt finishes its SSE stream, the result is written and flushed to CSV, then the process exits cleanly.
- **Second Ctrl+C** — force-exits immediately. Already-flushed rows are safe; only the in-flight prompt is lost.

You will never lose completed work. Each prompt result is flushed to disk the moment it finishes.

### Resume (prompt level)

Pass `--resume` to skip completed prompts and pick up where you left off:

```bash
uv run python run_evaluation.py \
    --provider ollama --model qwen3:8b --condition open \
    --temperature 0.0 --runs 10 --resume
```

Only prompts that completed **without errors** are skipped. Failed prompts get retried.

### Resume (matrix level)

`run_full_matrix.sh` tracks completed cells in `results/matrix_progress.log`. On re-run, cells logged as DONE are skipped entirely.

**Recovery after any interruption**: just run `bash run_full_matrix.sh` again. It picks up where it left off at both levels (matrix cell + prompt within cell).

### Retry logic

Transient errors (HTTP 429, 500, 502, 503, 529, timeout) trigger automatic retry with exponential backoff (10s → 20s → 40s → 80s → 160s, 5 attempts max). Non-retryable errors fail immediately and are recorded in the CSV for re-run via `--resume`.

## Monitoring Progress

### Log files

| File | Location | Purpose |
|------|----------|---------|
| `matrix_progress.log` | `results/` | One line per completed cell — **check this to see where you are** |
| `matrix_run.log` | `results/` | Full terminal output (survives terminal close) |
| `failed_runs.log` | `results/` | Failed cells only, for re-inspection |
| `result_provenance.csv` | `results/` | One row per completed run with metadata |

### Checking status mid-run

```bash
# How many cells are done?
wc -l results/matrix_progress.log

# Which cells are done?
cat results/matrix_progress.log

# Any failures?
cat results/failed_runs.log

# Count total evaluation rows across all result CSVs
find results -name '*.csv' -not -name 'result_provenance.csv' -not -path '*/archive/*' \
    -not -path '*/__archive/*' | xargs wc -l
```

### Expected cell count

Primary: 6 models × 4 temps × 2 conditions = **48 cells**
Satellite: 1 model × 4 temps × 2 conditions = **8 cells**
Total: **56 cells** in `matrix_progress.log` when complete.

## Scoring

After data collection, score results with the deterministic codebook:

```bash
uv run python score_results.py
```

This fills two columns in each CSV:
- **`result`**: PASS / PARTIAL / FAIL (tool selection correctness)
- **`parameters_correct`**: CORRECT / PARTIAL / INCORRECT / N/A

### Scoring tiers

| Tier | What it measures | How |
|------|-----------------|-----|
| **A** | Tool selection + parameter correctness | Automated via `codebook.py` rules |
| **B** | Cohort output correctness | Gold-standard comparison (Jaccard, F1) for P15, P19, P21, P24 |

Gold-standard reference cohorts live in `gold_standard_references/`.

See [SCORING_CODEBOOK.md](SCORING_CODEBOOK.md) for the full deterministic scoring rules.

## Directory Structure

```
plan_and_results/
├── README.md                      # This file
├── run_evaluation.py              # Evaluation harness (single model/condition)
├── run_full_matrix.sh             # Matrix runner (all models, resumable)
├── score_results.py               # Auto-scorer
├── codebook.py                    # Deterministic scoring rules (Python)
├── scorers.py                     # Scoring helper functions
├── gold_standards.py              # Gold-standard cohort comparison
├── analyze_results.py             # Statistical analysis + plots
├── routing_test_results.csv       # 33 evaluation prompts (the input)
├── routing_sessions.csv           # Session tracking
├── gold_standard_references/      # Reference cohort JSONs for Tier B
│   ├── P15_reference.json
│   ├── P19_reference.json
│   ├── P21_reference.json
│   └── P24_reference.json
├── results/                       # Output directory (see results/README.md)
├── archive/                       # Phase 1 pre-condition results
├── METHODS_MULTI_MODEL_EVALUATION.md  # Full methods paper draft
├── SCORING_CODEBOOK.md            # Scoring rules documentation
├── ROUTING_TEST_PLAN.md           # Original test plan
└── RESEARCH_NOTES_20260221.md     # Research decisions log
```

## Key Files

| File | Purpose |
|------|---------|
| `run_evaluation.py` | Core harness: sends prompts via SSE, parses tool calls, writes CSV |
| `run_full_matrix.sh` | Orchestrates all models/temps/conditions with progress tracking |
| `codebook.py` | Python-executable scoring rules for all 33 prompts |
| `score_results.py` | Walks result CSVs and applies codebook scoring |
| `routing_test_results.csv` | The 33 prompts with category codes and expected tools |
| `METHODS_MULTI_MODEL_EVALUATION.md` | Methods section draft for JAMIA submission |
| `SCORING_CODEBOOK.md` | Human-readable scoring codebook |
