# Evaluation Results

Output directory for the JAMIA multi-model evaluation harness.

## Directory Hierarchy

```
results/<creator>/<model>/temp_<t>/<condition>/<timestamp>.csv
```

Example:
```
results/anthropic/claude_sonnet_4_20250514/temp_0.0/open/20260222T143012Z.csv
results/qwen/qwen3_8b/temp_0.7/guided/20260222T150122Z.csv
```

- **creator**: LLM creator (anthropic, openai, qwen, meta)
- **model**: sanitized model name (colons/hyphens replaced with underscores)
- **temp_\<t\>**: temperature level (temp_0.0, temp_0.3, temp_0.7, temp_1.0, temp_default)
- **condition**: open or guided
- **timestamp**: UTC ISO 8601 (one CSV per evaluation run)

Each run produces one CSV. With 10 runs per cell, expect 10 CSVs per `<condition>/` directory.

## CSV Schema

| Column | Description |
|--------|-------------|
| `prompt_id` | Prompt identifier (1-33) |
| `category_code` | Category (C1-C8) |
| `category_name` | Human-readable category |
| `prompt` | The evaluation prompt text |
| `expected_tools` | Gold-standard tool chain |
| `condition` | open or guided |
| `provider` | LLM provider (ollama, claude, openai) |
| `model` | Model name |
| `temperature` | Sampling temperature |
| `run_number` | Run index within this cell |
| `result` | Scoring: PASS / PARTIAL / FAIL (filled by score_results.py) |
| `tools_called` | Pipe-delimited tool names the model called |
| `tool_arguments` | JSON array of argument dicts per tool call |
| `parameters_correct` | CORRECT / PARTIAL / INCORRECT / N/A (filled by score_results.py) |
| `latency_sec` | End-to-end prompt latency |
| `rounds` | Agent loop iterations |
| `text_response` | Model's text output (truncated to 500 chars) |
| `errors` | Pipe-delimited error codes (empty if successful) |
| `session_id` | Webapp session UUID |
| `notes` | Manual annotations |
| `timestamp` | UTC ISO 8601 when the row was written |

## Log Files

| File | Purpose |
|------|---------|
| `matrix_progress.log` | One timestamped line per completed matrix cell. Check this to see where a resumed run picks up. |
| `matrix_run.log` | Full terminal output from `run_full_matrix.sh` (append mode, survives terminal close). |
| `failed_runs.log` | Timestamped entries for cells that failed after retry. Re-run these individually. |
| `result_provenance.csv` | One row per completed run: file path, condition, model, temperature, run number, prompt counts, harness commit SHA, timestamp. |

## Archive Directories

| Directory | Contents |
|-----------|----------|
| `archive/` | Phase 1 evaluation results (pre-condition design, 13 models, single condition). Kept for reference but not used in the JAMIA analysis. |
| `__archive/` | Superseded runs from development iterations. |
| `archive/_excluded/` | Models excluded from the study (MedGemma, Moonshot) with reasons documented in its README.md. |
