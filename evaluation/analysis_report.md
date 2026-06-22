# Multi-Model Routing Evaluation Report

*4 study models, 33 prompts, 8 capability categories (C1-C8). DeepSeek V3 (pre-study feasibility build) is reported separately and excluded from all study statistics.*

## Summary

- **Models evaluated:** 4
- **Unique prompts:** 33 (8 capability categories)
- **Total evaluations:** 760
- **Scored:** 760 (760/760)
- **Unscored:** 0
- **Human-reviewed:** 110
- **Overall pass rate:** 81.6% [78.7%, 84.2%]
- **Overall pass+partial rate:** 89.6%
- **Mean latency:** 40.14s
- **Median latency:** 26.39s

## Table 1: Pass Rate by Model (95% Bayesian CI)

| Model | n | PASS | PARTIAL | FAIL | Pass % | 95% CI | Pass+Partial % |
|:------|--:|-----:|--------:|-----:|-------:|:------:|---------------:|
| claude/claude-haiku-4-5-20251001 | 190 | 159 | 16 | 15 | 83.7% | [78.1%, 88.6%] | 92.1% |
| claude/claude-sonnet-4-20250514 | 190 | 175 | 10 | 5 | 92.1% | [87.8%, 95.6%] | 97.4% |
| ollama/qwen3:14b | 190 | 132 | 25 | 33 | 69.5% | [62.8%, 75.8%] | 82.6% |
| ollama/qwen3:8b | 190 | 154 | 10 | 26 | 81.1% | [75.2%, 86.3%] | 86.3% |

## Table 2: Pass Rate by Capability Category

| Category | Name | Prompts | Scored | PASS | Pass % | 95% CI |
|:---------|:-----|--------:|-------:|-----:|-------:|:------:|
| C1 | Single Tool Selection | 6 | 120 | 119 | 99.2% | [96.1%, 100.0%] |
| C2 | Tool Disambiguation | 4 | 80 | 79 | 98.8% | [94.2%, 100.0%] |
| C3 | Intra-Server Chaining | 4 | 80 | 63 | 78.8% | [69.1%, 87.0%] |
| C4 | Cross-Server Chaining | 6 | 140 | 121 | 86.4% | [80.2%, 91.6%] |
| C5 | Parameter Construction | 4 | 100 | 24 | 24.0% | [16.2%, 32.8%] |
| C6 | Graceful Degradation | 3 | 60 | 54 | 90.0% | [80.9%, 96.5%] |
| C7 | Multi-Faceted Composition | 3 | 60 | 45 | 75.0% | [63.4%, 85.0%] |
| C8 | Cohort Construction | 3 | 120 | 115 | 95.8% | [91.3%, 98.9%] |

## Table 3: Model Comparison Matrix

| P# | Cat | claude/claude-haiku-4-5-20251001 | claude/claude-sonnet-4-20250514 | ollama/qwen3:14b | ollama/qwen3:8b |
|---:|:----|---: | ---: | ---: | ---: |
| 1 | C1 | 5/5 | 5/5 | 5/5 | 5/5 |
| 2 | C1 | 5/5 | 5/5 | 5/5 | 5/5 |
| 3 | C1 | 5/5 | 5/5 | 5/5 | 5/5 |
| 4 | C1 | 5/5 | 5/5 | 5/5 | 5/5 |
| 5 | C1 | 5/5 | 5/5 | 4/5 | 5/5 |
| 6 | C1 | 5/5 | 5/5 | 5/5 | 5/5 |
| 7 | C2 | 5/5 | 5/5 | 5/5 | 5/5 |
| 8 | C2 | 5/5 | 5/5 | 4/5 | 5/5 |
| 9 | C2 | 5/5 | 5/5 | 5/5 | 5/5 |
| 10 | C2 | 5/5 | 5/5 | 5/5 | 5/5 |
| 11 | C3 | 5/5 | 5/5 | 0/5 | 0/5 |
| 12 | C3 | 5/5 | 5/5 | 4/5 | 5/5 |
| 13 | C3 | 5/5 | 5/5 | 0/5 | 5/5 |
| 14 | C3 | 5/5 | 5/5 | 4/5 | 5/5 |
| 15 | C4 | 0/5 | 5/5 | 0/5 | 0/5 |
| 16 | C4 | 5/5 | 5/5 | 4/5 | 5/5 |
| 17 | C4 | 5/5 | 5/5 | 4/5 | 5/5 |
| 18 | C4 | 5/5 | 5/5 | 5/5 | 4/5 |
| 19 | C4 | 10/10 | 10/10 | 10/10 | 10/10 |
| 20 | C4 | 5/5 | 5/5 | 4/5 | 5/5 |
| 21 | C5 | 0/10 | 5/10 | 9/10 | 0/10 |
| 22 | C5 | 0/5 | 0/5 | 0/5 | 0/5 |
| 23 | C5 | 0/5 | 0/5 | 0/5 | 5/5 |
| 24 | C5 | 0/5 | 5/5 | 0/5 | 0/5 |
| 25 | C6 | 4/5 | 5/5 | 0/5 | 5/5 |
| 26 | C6 | 5/5 | 5/5 | 5/5 | 5/5 |
| 27 | C6 | 5/5 | 5/5 | 5/5 | 5/5 |
| 28 | C7 | 5/5 | 5/5 | 5/5 | 5/5 |
| 29 | C7 | 5/5 | 5/5 | 0/5 | 0/5 |
| 30 | C7 | 5/5 | 5/5 | 0/5 | 5/5 |
| 31 | C8 | 10/10 | 10/10 | 10/10 | 10/10 |
| 32 | C8 | 10/10 | 10/10 | 7/10 | 10/10 |
| 33 | C8 | 10/10 | 10/10 | 8/10 | 10/10 |

## Table 4: Latency by Model (seconds)

| Model | Mean | Median | Min | Max |
|:------|-----:|-------:|----:|----:|
| claude/claude-haiku-4-5-20251001 | 8.23 | 6.95 | 2.81 | 35.23 |
| claude/claude-sonnet-4-20250514 | 26.67 | 22.24 | 5.47 | 145.82 |
| ollama/qwen3:14b | 58.78 | 54.7 | 1.31 | 162.84 |
| ollama/qwen3:8b | 66.89 | 39.56 | 3.61 | 623.01 |

## Table 5: Cross-Server Chain Success (C4)

| Model | n | PASS | Pass % | 95% CI |
|:------|--:|-----:|-------:|:------:|
| claude/claude-haiku-4-5-20251001 | 35 | 30 | 85.7% | [72.1%, 95.5%] |
| claude/claude-sonnet-4-20250514 | 35 | 35 | 100.0% | [92.1%, 100.0%] |
| ollama/qwen3:14b | 35 | 27 | 77.1% | [62.0%, 89.3%] |
| ollama/qwen3:8b | 35 | 29 | 82.9% | [68.6%, 93.5%] |

## Table 6: Parameter Correctness by Model

| Model | n | CORRECT | PARTIAL | INCORRECT | Correct % |
|:------|--:|--------:|--------:|----------:|----------:|
| claude/claude-haiku-4-5-20251001 | 160 | 125 | 35 | 0 | 78.1% |
| claude/claude-sonnet-4-20250514 | 170 | 140 | 30 | 0 | 82.4% |
| ollama/qwen3:14b | 142 | 112 | 30 | 0 | 78.9% |
| ollama/qwen3:8b | 149 | 119 | 30 | 0 | 79.9% |

## Table: Failure Mode Distribution by Model

| Model | TOOL_OMISSION | WRONG_TOOL | Total |
|:------|---: | ---: | ---: |
| claude/claude-haiku-4-5-20251001 | 15 | 20 | 35 |
| claude/claude-sonnet-4-20250514 | 5 | 15 | 20 |
| ollama/qwen3:14b | 43 | 15 | 58 |
| ollama/qwen3:8b | 26 | 20 | 46 |
| **Total** | 89 | 70 | 159 |

## Table: Open vs Guided Condition Comparison

Guided prompts (P19, P21, P31-P33): raw SQL hidden, forcing structured tool paths.

| Model | Open Pass % (n) | Guided Pass % (n) | Delta |
|:------|----------------:|-------------------:|------:|
| claude/claude-haiku-4-5-20251001 | 80.0% (20/25) | 80.0% (20/25) | +0.0pp |
| claude/claude-sonnet-4-20250514 | 100.0% (25/25) | 80.0% (20/25) | -20.0pp |
| ollama/qwen3:14b | 80.0% (20/25) | 96.0% (24/25) | +16.0pp |
| ollama/qwen3:8b | 80.0% (20/25) | 80.0% (20/25) | +0.0pp |

## Table 7: Pass Rate by Model × Temperature

| Model | T=0.0 |
|:------|------: |
| claude/claude-haiku-4-5-20251001 | 83.7% (159/190) |
| claude/claude-sonnet-4-20250514 | 92.1% (175/190) |
| ollama/qwen3:14b | 69.5% (132/190) |
| ollama/qwen3:8b | 81.1% (154/190) |

## Table 8: Pass Rate by Category × Temperature

| Category | Name | T=0.0 |
|:---------|:-----|------: |
| C1 | Single Tool Selection | 99.2% |
| C2 | Tool Disambiguation | 98.8% |
| C3 | Intra-Server Chaining | 78.8% |
| C4 | Cross-Server Chaining | 86.4% |
| C5 | Parameter Construction | 24.0% |
| C6 | Graceful Degradation | 90.0% |
| C7 | Multi-Faceted Composition | 75.0% |
| C8 | Cohort Construction | 95.8% |

## Table 9: Trajectory Diversity

Mean proportion of unique tool-call sequences per prompt (1.0 = all runs identical, lower = more diverse trajectories).

| Model | T=0.0 |
|:------|------: |
| claude/claude-haiku-4-5-20251001 | 0.212 |
| claude/claude-sonnet-4-20250514 | 0.255 |
| ollama/qwen3:14b | 0.276 |
| ollama/qwen3:8b | 0.212 |

## Table 10: Temperature Sensitivity (Pass Rate at T=0.0 vs T=1.0)

| Model | T=0.0 Pass % | T=1.0 Pass % | Delta | Direction |
|:------|-------------:|-------------:|------:|:----------|
| claude/claude-haiku-4-5-20251001 | - | - | - | - |
| claude/claude-sonnet-4-20250514 | - | - | - | - |
| ollama/qwen3:14b | - | - | - | - |
| ollama/qwen3:8b | - | - | - | - |

## Table 11: Pairwise Model Comparison (Fisher's Exact Test)

*scipy not available — install with `uv add scipy` to enable this table.*

## Pre-study feasibility build (EXCLUDED from all study statistics)

DeepSeek V3 was run as a *pre-study feasibility build* to assess whether a third-party cloud model could be included. It ran under the open condition only, with runs truncated by API connection failures. It is **not** part of the four-model study and is excluded from every table above.

| Model (pre-study) | n | PASS | Pass % |
|:--|--:|--:|--:|
| deepseek/deepseek-chat | 59 | 53 | 89.8% |
