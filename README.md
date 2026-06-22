# Multi-Model Tool Routing Evaluation for an MCP-Native OHDSI Agent

Reproducibility repository for the study *"Multi-Model Tool Routing Evaluation for an MCP-Native OHDSI Agent"* (Smith, Marquez, Rhodes, Zhang, Budiman; Emory University), to appear in the **AMIA 2026 Annual Symposium** proceedings.

The study evaluates how reliably large language models (LLMs) route tool calls for Observational Medical Outcomes Partnership (OMOP) Common Data Model (CDM) access, using a three-server Model Context Protocol (MCP) architecture against a 100,000-patient Synthea OMOP CDM. Across **33 prompts × 8 capability categories × 5 LLMs × 2 conditions (820 evaluations)**, the overall tool-routing pass rate was 82.1%.

> **Provenance.** This repository is a curated snapshot of the OHDSI agent **as the evaluation was run and submitted** (source commit `0aaf09b`, 2026-03-12). Later development of the agent (graph tools, semantic search, concept-id staging) post-dates the evaluation and is intentionally **not** included, so that the code here matches the system the paper describes.

## What this repository contains

```
servers/
  ohdsi-vocab/        # MCP server #1 — vocabulary search, concept hierarchy,
                      #   phenotype/query libraries, CDM schema, concept-set preview (12 tools)
  circe-compiler/     # MCP server #2 — CIRCE cohort construction + deterministic
                      #   compilation to executable SQL (correct-by-construction) (6 tools)
  omop_vocab_core/    # shared library used by ohdsi-vocab
  omcp/               # MCP server #3 — read-only SQL execution (2 tools). Vendored
                      #   third-party, derived from fastomop/omcp (MIT);
                      #   see servers/omcp/VENDORED.md
webapp/               # FastAPI "LLM client": a ReAct-style agentic tool-use loop that
                      #   connects to the three MCP servers and drives the models
evaluation/           # the evaluation harness, scoring codebook, prompts, gold
                      #   standards, scored result CSVs, and analysis scripts
```

## The three-server architecture

The LLM client (`webapp/`) presents a single unified tool surface (20 tools; 19 evaluated) drawn from three independently-running MCP servers. A key safety property is that the **circe-compiler is correct-by-construction**: the LLM supplies only a simplified cohort specification, and the deterministic CIRCE engine — not the LLM — emits the executable SQL. The evaluation runs two conditions:

- **Open** — all 19 tools available, including direct SQL (`Select_Query`).
- **Guided** — the two SQL tools are hidden (17 tools), forcing data-producing queries through the compiler's correct-by-construction pipeline.

## Evaluation harness (`evaluation/`)

- `routing_test_results.csv` — the 33 evaluation prompts (8 categories, C1–C8) with expected tool sequences.
- `SCORING_CODEBOOK.md` / `codebook.py` — deterministic per-prompt scoring rules (tool selection: PASS/PARTIAL/FAIL; parameter correctness: CORRECT/PARTIAL/INCORRECT).
- `scorers.py`, `score_results.py` — automated scorer and the 11-category failure-mode taxonomy.
- `gold_standards.py`, `gold_standard_references/` — Tier-B gold-standard cohorts (Jaccard / F1).
- `run_evaluation.py` — the harness that sends each prompt to the webapp and records results.
- `analyze_results.py`, `analysis_report.md` — aggregation and the reported tables.
- `results/` — the scored per-model result CSVs underlying the published numbers.
- `flagged_for_review.csv` — the rows routed to manual human review.

## Prerequisites

- **macOS or Linux.**
- **[`uv`](https://docs.astral.sh/uv/)** — Python package manager (each component has its own `pyproject.toml` + `uv.lock`; `uv` will fetch Python 3.13).
- **Docker + Docker Compose** — only for the Langfuse observability stack (full-parity mode).
- **`lsof`** — the stack runner uses it to manage ports (preinstalled on macOS and most Linux).
- **Local models:** [Ollama](https://ollama.com) with `qwen3:8b` and `qwen3:14b` pulled (`ollama pull qwen3:8b`).
- **Cloud models:** an Anthropic API key (required for the smoke test); OpenAI / Google / DeepSeek keys optional.

## Data — the evaluation database (do this first)

The three servers query a 100,000-patient **Synthea OMOP CDM v5.4** DuckDB with schemas `main_vocab` (vocabulary) and `main_cdm` (clinical). It is **not** in the repo (multi-GB) and is **rebuilt locally** from an archived source deposit plus your own copy of the OMOP vocabularies.

The Zenodo deposit (DOI [10.5281/zenodo.18726343](https://doi.org/10.5281/zenodo.18726343)) holds the **exact as-run inputs** — not a prebuilt database, and deliberately **no licensed vocabulary**:

- `synthea_100k_raw_csvs.tar.zst` — the 18 as-run Synthea CSVs (the synthetic population behind the paper's numbers; ~111,891 persons),
- `vocabulary.csv` — the 83-row OMOP vocabulary version manifest (which Athena versions to fetch),
- `gold_standard_references/`, `config/` (dbt project/profiles + `regenerate-synthea-100k.sh`), `database_summary.json`, `README.md`, `checksums.sha256`.

Steps:

1. **Download the deposit** (DOI above) and verify it against `checksums.sha256`.
2. **Bring your own vocabulary.** From [OHDSI Athena](https://athena.ohdsi.org/), download the OMOP vocabularies matching `vocabulary.csv` (v5.0, 27-Feb-2025), accepting the SNOMED CT / CPT4 licenses on Athena yourself (these are intentionally **not** redistributed). Place them where the config expects (e.g., `vocab_parquet/`).
3. **Build the DuckDB.** From the **unpacked deposit** (this build tooling ships with the deposit, not in this repo), run `config/regenerate-synthea-100k.sh` — it drives the upstream **OHDSI/dbt-synthea** package (`@b948686`) to load `main_cdm` from the archived Synthea CSVs and `main_vocab` from your Athena vocabulary, producing the OMOP CDM v5.4 database.
4. **Point the stack at it.** Set `DUCKDB_PATH` in your `.env` to the resulting file (the runner exports it to the servers as `OHDSI_DUCKDB_PATH` / `DB_PATH`).

Synthea generation was **unseeded**, so regenerating from scratch would yield a *different* population — the archived CSVs **are** the dataset, and rebuilding from them reproduces the exact reference cohort counts.

## Quickstart

```bash
git clone https://github.com/Emory-OMOP/ohdsi-agent-routing-eval
cd ohdsi-agent-routing-eval
cp env.example .env        # edit: DUCKDB_PATH, BETA_PASSKEY, JWT_SECRET, ANTHROPIC_API_KEY, Langfuse keys
```

### Run WITH Langfuse (full parity — what produced the paper's runs)

```bash
# 1) Bring up Langfuse (web/worker/postgres/clickhouse/minio/redis on :3000)
cd langfuse
cp env.example .env         # edit secrets (generation hints in the file)
docker compose up -d        # then open http://localhost:3000
#    Copy the project keys (LANGFUSE_INIT_PROJECT_PUBLIC_KEY/_SECRET_KEY) into the
#    repo-root .env as LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY. Keep LANGFUSE_ENABLED=true.
cd ..

# 2) Start the 3 MCP servers + webapp and run the matrix (4 primary models × 2 conditions × 5 runs)
cd evaluation
bash run_arxiv_matrix.sh --dry-run   # preview the plan first
bash run_arxiv_matrix.sh             # starts :8001/:8002/:8003/:8000, then runs
```

### Run WITHOUT Langfuse (lean — quick stack test, or you already capture metadata)

```bash
# In the repo-root .env set:  LANGFUSE_ENABLED=false   (and skip the langfuse/ stack)
cd evaluation
bash run_arxiv_matrix.sh             # same runner; the webapp starts with tracing off
```

(`omcp` already runs with its own tracing off in the runner via `ENABLE_LANGFUSE=false`.)

### Smoke test (prove the pipeline end-to-end with just an Anthropic key)

`run_arxiv_matrix.sh` runs the *full* matrix. For a quick end-to-end check, start the stack with the runner (or the four server commands it contains), then hit the webapp directly with one model over a few prompts:

```bash
cd evaluation
uv run --with httpx python run_evaluation.py \
  --provider claude --model claude-haiku-4-5-20251001 \
  --condition open --runs 1 --prompts 1,2,3
```

Requires only `ANTHROPIC_API_KEY`, the DB on disk, and the stack running. Outputs land under `evaluation/results/<provider>/<model>/...`.

### Score and analyze

```bash
cd evaluation
uv run python score_results.py                                   # apply the codebook
uv run python gold_standards.py score-all --db ../synthea_omop_etl.duckdb   # Tier B
uv run --with scipy python analyze_results.py                    # regenerate the tables (scipy → Fisher table + exact Beta CIs)
```

### Full reproduction vs. smoke test

- **Smoke test:** one model (Anthropic), a few prompts — needs only an Anthropic key.
- **Full reproduction:** all five models — Claude Sonnet 4 + Claude Haiku 4.5 (Anthropic keys), Qwen3 8B + Qwen3 14B (Ollama, local), and the DeepSeek V3 pilot (DeepSeek key, **open condition only**; run separately — it is not in the four-model matrix). Each provider needs its own key/runtime; there is no single-key full repro.

## Status

- **License: Apache-2.0** (see `LICENSE`). The repository's own code is licensed Apache-2.0; the vendored `servers/omcp/` retains its upstream MIT license (see `servers/omcp/LICENSE` and `NOTICE.md`).
- **Canonical location:** the `Emory-OMOP` GitHub organization — `https://github.com/Emory-OMOP/ohdsi-agent-routing-eval`. The repository may go public at or before the paper's publication.

## Citation

If you use this evaluation, please cite the AMIA 2026 paper (full citation to be added on publication) and the Zenodo dataset (DOI above).

Third-party components are credited in [`NOTICE.md`](NOTICE.md).
