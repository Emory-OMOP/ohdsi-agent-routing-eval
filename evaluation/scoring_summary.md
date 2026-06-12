# Scoring Summary

*Generated: 2026-03-11 01:19 UTC*

**WARNING: 246 rows have provisional scores pending human review.**
Run `uv run python review_flagged.py` to complete review.
These rows are EXCLUDED from all statistics below.

## Overall

- Total rows: 1693
- Scored: 1693
- PASS: 1176 (69.5%)
- PARTIAL: 99 (5.8%)
- FAIL: 418 (24.7%)

## Pass Rate by Model

| Model | n | PASS | PARTIAL | FAIL | Pass % | Pass+Partial % |
|:------|--:|-----:|--------:|-----:|-------:|---------------:|
| claude/claude-haiku-4-5-20251001 [guided] | 50 | 20 | 0 | 30 | 40.0% | 40.0% |
| claude/claude-haiku-4-5-20251001 [open] | 300 | 110 | 15 | 175 | 36.7% | 41.7% |
| claude/claude-sonnet-4-20250514 [guided] | 73 | 37 | 0 | 36 | 50.7% | 50.7% |
| claude/claude-sonnet-4-20250514 [open] | 863 | 698 | 55 | 110 | 80.9% | 87.3% |
| deepseek/deepseek-chat [open] | 52 | 47 | 2 | 3 | 90.4% | 94.2% |
| ollama/qwen3:14b [guided] | 26 | 24 | 0 | 2 | 92.3% | 92.3% |
| ollama/qwen3:14b [open] | 164 | 111 | 17 | 36 | 67.7% | 78.0% |
| ollama/qwen3:8b [guided] | 25 | 20 | 0 | 5 | 80.0% | 80.0% |
| ollama/qwen3:8b [open] | 140 | 109 | 10 | 21 | 77.9% | 85.0% |

## Pass Rate by Category

| Category | Name | n | PASS | Pass % |
|:---------|:-----|--:|-----:|-------:|
| C1 | Single Tool Selection | 332 | 286 | 86.1% |
| C2 | Tool Disambiguation | 218 | 188 | 86.2% |
| C3 | Intra-Server Chaining | 216 | 170 | 78.7% |
| C4 | Cross-Server Chaining | 355 | 271 | 76.3% |
| C5 | Parameter Construction | 251 | 71 | 28.3% |
| C6 | Graceful Degradation | 30 | 0 | 0.0% |
| C7 | Multi-Faceted Composition | 36 | 0 | 0.0% |
| C8 | Cohort Construction | 255 | 190 | 74.5% |

## Pass Rate by Prompt

| Prompt | Category | n | PASS | Pass % |
|-------:|:---------|--:|-----:|-------:|
| 1 | C1 | 56 | 47 | 83.9% |
| 2 | C1 | 56 | 48 | 85.7% |
| 3 | C1 | 55 | 48 | 87.3% |
| 4 | C1 | 55 | 48 | 87.3% |
| 5 | C1 | 55 | 47 | 85.5% |
| 6 | C1 | 55 | 48 | 87.3% |
| 7 | C2 | 55 | 48 | 87.3% |
| 8 | C2 | 55 | 46 | 83.6% |
| 9 | C2 | 54 | 47 | 87.0% |
| 10 | C2 | 54 | 47 | 87.0% |
| 11 | C3 | 54 | 37 | 68.5% |
| 12 | C3 | 54 | 46 | 85.2% |
| 13 | C3 | 54 | 41 | 75.9% |
| 14 | C3 | 54 | 46 | 85.2% |
| 15 | C4 | 54 | 27 | 50.0% |
| 16 | C4 | 53 | 42 | 79.2% |
| 17 | C4 | 53 | 43 | 81.1% |
| 18 | C4 | 53 | 43 | 81.1% |
| 19 | C4 | 89 | 71 | 79.8% |
| 20 | C4 | 53 | 45 | 84.9% |
| 21 | C5 | 90 | 38 | 42.2% |
| 22 | C5 | 54 | 1 | 1.9% |
| 23 | C5 | 54 | 5 | 9.3% |
| 24 | C5 | 53 | 27 | 50.9% |
| 25 | C6 | 10 | 0 | 0.0% |
| 26 | C6 | 10 | 0 | 0.0% |
| 27 | C6 | 10 | 0 | 0.0% |
| 28 | C7 | 9 | 0 | 0.0% |
| 29 | C7 | 19 | 0 | 0.0% |
| 30 | C7 | 8 | 0 | 0.0% |
| 31 | C8 | 85 | 65 | 76.5% |
| 32 | C8 | 85 | 62 | 72.9% |
| 33 | C8 | 85 | 63 | 74.1% |

## Failure Mode Distribution

| Mode | Count | Description |
|:-----|------:|:------------|
| TOOL_OMISSION | 439 | Required tool never called |
| WRONG_TOOL | 75 | Called a semantically different tool |
| TIMEOUT | 3 | 300s limit reached |

## Execution Validity (Tier A — SQL-Generating Prompts)

- VALID: 0
- INVALID: 0
- ERROR: 8
- Pending: 0

