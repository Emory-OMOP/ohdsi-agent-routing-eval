# Provenance — "as-run" component snapshot

This repository is a faithful snapshot of the system **as the AMIA 2026
evaluation actually ran and was submitted**. Each component is taken from a
specific upstream commit at, or immediately before, the evaluation — not from
current `HEAD`. Later development (graph tools, semantic search, concept-id
staging, and the MMM vocabulary-mapping work) post-dates the evaluation and is
deliberately excluded.

| Component (here) | Upstream repository | Pinned commit | Commit date | Notes |
|---|---|---|---|---|
| `servers/ohdsi-vocab/` | `emory_ohdsi_agent` (`mcp_server/`) | `0aaf09b` | 2026-03-12 | Vocabulary MCP server (12 tools), eval-as-submitted state |
| `servers/circe-compiler/` | `emory_ohdsi_agent` (`circe_compiler/`) | `0aaf09b` | 2026-03-12 | Cohort construction + deterministic compilation (6 tools) |
| `servers/omop_vocab_core/` | `emory_ohdsi_agent` (`omop_vocab_core/`) | `0aaf09b` | 2026-03-12 | Shared library used by `ohdsi-vocab` |
| `webapp/` | `emory_ohdsi_agent` (`webapp/`) | `0aaf09b` | 2026-03-12 | FastAPI LLM client / ReAct tool-use loop |
| `evaluation/` | `emory_ohdsi_agent` (`publications/jamia/plan_and_results/`) | `0aaf09b` | 2026-03-12 | Harness, scoring codebook, prompts, gold standards, scored results |
| `servers/omcp/` | `fastomop/omcp` | `4922d41` (base) | 2025-12-09 | Read-only SQL execution; MIT-licensed. Modified for this evaluation — see note below |

## Pulled upstream data and libraries (versions)

These are external libraries and datasets the evaluation depended on but does
not vendor as source. Their versions are recorded here for reproducibility.

| Component | Upstream | Version / commit | Pinned? |
|---|---|---|---|
| OHDSI PhenotypeLibrary | OHDSI/PhenotypeLibrary (Apache-2.0) | `main` HEAD, pulled 2026-02-17, commit unrecorded | No — floating HEAD (see forward-fix) |
| OHDSI QueryLibrary | OHDSI/QueryLibrary (Apache-2.0) | `master` HEAD, pulled 2026-02-17, commit unrecorded | No — floating HEAD |
| Synthea | synthetichealth/synthea (Apache-2.0, MITRE) | v3.0.0 | Yes (tag) |
| OMOP CDM | OHDSI/CommonDataModel (Apache-2.0) | v5.4 | Yes (spec version) |
| OMOP Vocabularies (Athena) | OHDSI Athena; per-source licenses | v5.0, 27-Feb-2025 | Yes (release) — do not redistribute vocab files |
| dbt-synthea (ETL) | OHDSI/dbt-synthea (Apache-2.0) | upstream commit `b948686` | Yes (commit) — not redistributed here |

**Forward-fix (reproducibility caveat).** PhenotypeLibrary and QueryLibrary were
pulled from upstream HEAD by `servers/ohdsi-vocab/scripts/download_phenotype_library.sh`
and `download_query_library.sh`; those scripts do not pin a commit, so the exact
versions used in the evaluation are unrecorded and cannot be reconstructed from
the (git-ignored) on-disk copies. Pin specific commits/tags in those download
scripts for fully reproducible setup.

## omcp derivation

`servers/omcp/` is derived from **`fastomop/omcp@4922d41`** (2025-12-09, MIT
license; see `servers/omcp/LICENSE`). For this evaluation it was modified as
follows:

- Removed the `Lookup_Drug` and `Lookup_Condition` tools, leaving the two tools
  the study evaluated (`Select_Query` and `Get_Information_Schema`), and added
  schema files.
- Switched the database connection to DuckDB connect-per-query (resolving lock
  contention).
- Upgraded the MCP dependency to ≥1.26 and added streamable-HTTP transport
  support.

The MIT license requires that the copyright and permission notice travel with
the code; it is preserved verbatim in `servers/omcp/LICENSE`.

## Explicitly excluded (post-dates the evaluation)

- `emory_ohdsi_agent` commit `871d961` (2026-04-09, "Add graph tools, semantic
  search, and compound vocabulary tools") and everything after it. That later
  graph-navigation, semantic-search, and concept-id-staging functionality did
  not exist at evaluation time and is **not** part of this paper's system.
- The Mind Meets Machine (MMM) vocabulary-mapping work, which is a separate
  artifact with its own repository.

## Modifications applied during extraction

The extracted files are verbatim from the pinned commits, with these
sanitizations for public release (no behavioral changes):

- Removed an internal agent-instructions file (`.claude/CLAUDE.md`), an internal
  dated research-notes document, and two Langfuse helper shell scripts that
  carried development-placeholder keys.
- Genericized three internal references: an internal schema-name list in the
  webapp system prompt, an absolute local path and a 1Password usage note in a
  runner script, and an absolute path prefix in the manual-review tracking CSV.
- Removed superseded/intermediate result archives and run logs from
  `evaluation/results/`, keeping the final scored result CSVs for the five
  published models (Claude Sonnet 4, Claude Haiku 4.5, Qwen3 8B, Qwen3 14B, and
  the DeepSeek V3 pilot).
- Removed an earlier exploratory result archive (2026-02-21 runs across a wider
  set of models that were screened but **not** part of the published
  five-model evaluation), to keep the repository scoped to the paper's study.
- Did not commit the multi-gigabyte evaluation database or omcp's bundled
  synthetic-data stub. The database is **rebuilt** from a Zenodo deposit (DOI
  10.5281/zenodo.18726343), which holds the exact as-run inputs — the 18 Synthea
  CSVs (~111,891 persons), the 83-row OMOP `vocabulary` version manifest, the
  gold-standard references, and a `config/` with the dbt project and
  `regenerate-synthea-100k.sh`. It contains **no prebuilt DuckDB and no licensed
  vocabulary** (SNOMED CT / CPT4 are excluded; users fetch matching Athena
  vocabularies under those licenses themselves). dbt-synthea loads `main_cdm`
  from the CSVs and `main_vocab` from the user's Athena vocabulary. Synthea
  generation was unseeded, so the archived CSVs — not a re-generation — reproduce
  the exact cohort counts.
- Adjusted layout-dependent path resolution to match the flattened public
  structure (the source nested `mcp_server/`, `circe_compiler/`, and the eval
  harness under `publications/jamia/plan_and_results/`; here they are
  `servers/ohdsi-vocab/`, `servers/circe-compiler/`, and `evaluation/`). The
  runner `run_arxiv_matrix.sh` (`REPO`, server directories, Tier-B DB path) and a
  few `Path(__file__).parents[...]` repo-root computations in `gold_standards.py`
  and the circe server were re-indexed so defaults resolve correctly. Behavior is
  unchanged when the documented environment variables are set.
- Vendored the **Langfuse** self-hosted observability stack (`langfuse/`,
  Docker Compose: web/worker + Postgres/ClickHouse/MinIO/Redis), which the webapp
  and `omcp` send traces to. The source directory's 1Password-injected secrets
  file (`.env.op`) was **not** vendored; the compose header was de-internalized;
  and an `env.example` with placeholder secrets was added. Langfuse runs by
  default in the full stack and can be turned off (`LANGFUSE_ENABLED=false`) for a
  lean run.
- Removed inline Langfuse placeholder keys from `run_arxiv_matrix.sh` (now
  env-only) so no secret-shaped literals are committed.

## Note for reviewers

The vendored webapp configuration default for `max_tool_rounds` is 50, while the
manuscript reports a maximum of 10 rounds for the evaluation. The published value
(10) is reflected in `env.example` (`MAX_TOOL_ROUNDS=10`); the evaluation set this
via environment override. Confirm against run provenance if exact reproduction is
required.
