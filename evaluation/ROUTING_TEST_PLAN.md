# Evaluation Prompt Reference

> **Source of truth**: `routing_test_results.csv`
> This document summarizes the 33 evaluation prompts and their expected tool chains.
> Always treat the CSV as authoritative — this markdown is a human-readable reference.

---

## Category Summary

| Code | Category | Prompts | Description |
|------|----------|---------|-------------|
| C1 | Single Tool Selection | P01–P06 | Unambiguous single-tool requests |
| C2 | Tool Disambiguation | P07–P10 | Requires choosing between similar tools |
| C3 | Intra-Server Chaining | P11–P14 | Multi-step chains within one MCP server |
| C4 | Cross-Server Chaining | P15–P20 | Chains spanning ohdsi-vocab, circe-compiler, or omcp |
| C5 | Parameter Construction | P21–P24 | Correct parameter extraction and forwarding |
| C6 | Graceful Degradation | P25–P27 | Error handling and empty results |
| C7 | Multi-Faceted Composition | P28–P30 | Parallel or branching tool use |
| C8 | Cohort Construction | P31–P33 | End-to-end cohort building via build_cohort_definition |

---

## Condition Design

Each prompt is evaluated under two conditions:

| Condition | Available tools | Purpose |
|-----------|----------------|---------|
| **open** | All 20 tools (including Select_Query, Get_Information_Schema) | Baseline — full flexibility |
| **guided** | 18 tools (no Select_Query, no Get_Information_Schema) | Forces CIRCE pipeline for cohort queries |

Only C4/C5/C8 prompts that involve SQL or cohort construction differ meaningfully between conditions. C1–C3 and C6 are condition-invariant.

Guided condition applies to prompts: P15, P16, P17, P18, P19, P20, P21, P22, P23, P24, P31, P32, P33.

---

## Scoring Tiers

| Tier | Dimension | Applies to | Metric |
|------|-----------|------------|--------|
| Tool Selection | PASS / PARTIAL / FAIL | All 33 prompts | Were the right tools called? |
| Parameter Correctness | CORRECT / PARTIAL / INCORRECT | All 33 prompts | Were arguments correct? |
| Tier A — Execution Validity | Valid / Invalid / N/A | SQL-generating prompts (P15, P19–P24, P27, P29–P33) | Does the SQL run and return rows? |
| Tier B — Gold Standard | Jaccard / F1 | Gold standard prompts (P15, P19, P21, P24, P31–P33) | Patient set overlap with reference |

See `SCORING_CODEBOOK.md` for per-prompt scoring rules.

---

## C1: Single Tool Selection (P01–P06)

The model must select exactly the right tool for an unambiguous request.

| ID | Prompt | Expected Tool(s) |
|----|--------|-------------------|
| P01 | Find peer-reviewed cohort definitions for atrial fibrillation | `search_phenotypes` |
| P02 | Show me community SQL query templates for drug exposure | `search_query_patterns` |
| P03 | Get phenotype 77 | `get_phenotype(77)` |
| P04 | Look up the details for OMOP concept 201826 | `get_concept([201826])` |
| P05 | What are the relationships for concept 201826? Show me what it maps to. | `get_concept_relationships(201826)` |
| P06 | Preview concept set [201826, 4193704] with descendants included | `preview_concept_set([201826,4193704], include_descendants=True)` |

---

## C2: Tool Disambiguation (P07–P10)

The model must choose the correct tool when multiple tools could plausibly apply.

| ID | Prompt | Expected Tool(s) |
|----|--------|-------------------|
| P07 | What is the standard SNOMED concept for Type 2 Diabetes? | `search_concepts` |
| P08 | What are the descendants of concept 201826? | `get_concept_descendants(201826)` |
| P09 | What broader categories does concept 4193704 fall under in the SNOMED hierarchy? | `get_concept_ancestors(4193704)` |
| P10 | What columns does the measurement table have? | `get_table_schema("measurement")` |

---

## C3: Intra-Server Chaining (P11–P14)

Multi-step tool chains within a single MCP server (ohdsi-vocab).

| ID | Prompt | Expected Chain |
|----|--------|----------------|
| P11 | Find a peer-reviewed cohort for Type 2 Diabetes and show me its full definition | `search_phenotypes` → `get_phenotype` |
| P12 | What SQL patterns exist for drug exposure, and show me the best one | `search_query_patterns` → `get_query` |
| P13 | Look up concept 313217 and show me all its descendants | `get_concept` → `get_concept_descendants` |
| P14 | Find the standard concept for aspirin, then show me what drug ingredients it maps to | `search_concepts` → `get_concept_relationships` |

---

## C4: Cross-Server Chaining (P15–P20)

Tool chains spanning multiple MCP servers.

| ID | Prompt | Expected Chain | Servers |
|----|--------|----------------|---------|
| P15 | Find a heart failure phenotype and compile it to SQL | `search_phenotypes` → `get_phenotype` → `compile_cohort_definition` | vocab → circe |
| P16 | Validate the CIRCE JSON for phenotype 10 | `get_phenotype` → `validate_cohort_definition` | vocab → circe |
| P17 | Get phenotype 288 and analyze how complex it is | `get_phenotype` → `analyze_cohort_complexity` | vocab → circe |
| P18 | Preview what phenotype 519 would do without executing it | `get_phenotype` → `cohort_dry_run` | vocab → circe |
| P19 | How many patients have Type 2 Diabetes in our database? | `search_concepts` → `Select_Query` | vocab → omcp |
| P20 | Show me the drug_exposure table schema, then count the rows | `get_table_schema` → `Select_Query` | vocab → omcp |

**Note on P15–P18**: These require the model to pass large CIRCE JSON from `get_phenotype` output into circe-compiler tool inputs. This is a known pass-through bottleneck — see tool design improvements below.

---

## C5: Parameter Construction (P21–P24)

The model must extract and forward correct parameters across tool calls.

| ID | Prompt | Expected Chain |
|----|--------|----------------|
| P21 | Write a query to find all diabetes conditions using standard concepts | `search_concepts(standard_only=True)` → `Select_Query` |
| P22 | Compile phenotype 519 to PostgreSQL, then transpile to DuckDB | `get_phenotype` → `compile_cohort_definition(dialect=postgresql)` → `transpile_sql_dialect(source=postgresql,target=duckdb)` |
| P23 | Search for hypertension concepts, preview the set with descendants, then compile a cohort | `search_concepts` → `preview_concept_set` → `compile_cohort_definition` |
| P24 | What are the top 10 most common conditions in our database? Use proper table schema. | `get_table_schema` → `Select_Query` |

---

## C6: Graceful Degradation (P25–P27)

Error handling, empty results, and recovery.

| ID | Prompt | Expected Behavior |
|----|--------|-------------------|
| P25 | Get phenotype 99999 | `get_phenotype(99999)` → not found; suggests search |
| P26 | Search phenotypes for quantum computing | `search_phenotypes` → empty result; reports cleanly |
| P27 | Run this query: SELECT * FROM nonexistent_table LIMIT 5 | `Select_Query` → error; explains the failure |

---

## C7: Multi-Faceted Composition (P28–P30)

Prompts requiring parallel or branching tool use to address multiple sub-questions.

| ID | Prompt | Expected Tools |
|----|--------|----------------|
| P28 | I have concept set [201826, 4193704] -- what clinical domains do they cover and are there published phenotypes using them? | `get_concept` + `search_phenotypes` |
| P29 | Compare the OHDSI community's approach to drug cost analysis with what's in our database | `search_query_patterns` + `Select_Query` |
| P30 | Build a cohort of patients with chronic kidney disease: find SNOMED concepts, check existing phenotypes, and if you find one, analyze its complexity | `search_concepts` + `search_phenotypes` + `get_phenotype` → `analyze_cohort_complexity` |

---

## C8: Cohort Construction (P31–P33)

End-to-end cohort building using `build_cohort_definition`. These are the most complex prompts, requiring concept lookup followed by structured cohort specification.

| ID | Prompt | Expected Chain | Gold Standard |
|----|--------|----------------|---------------|
| P31 | Build a cohort of patients with their first Type 2 Diabetes diagnosis with 365 days prior observation. Look up the concept first. | `search_concepts` → `build_cohort_definition` | 7,164 patients |
| P32 | Build a cohort of hypertension patients excluding anyone with prior chronic kidney disease. Find the concepts first. | `search_concepts` → `build_cohort_definition` | 27,257 patients |
| P33 | Build a cohort of T2DM patients aged 18-65 who received Metformin within 365 days before diagnosis. Look up concepts first. | `search_concepts` → `build_cohort_definition` | 1,531 patients |

---

## Known Pass-Through Bottlenecks

Several prompts require the model to relay large JSON payloads between tool outputs and inputs. Smaller models (deepseek-chat, qwen) fail at this mechanical task:

| Chain | Affected Prompts | Payload Size | Status |
|-------|-----------------|--------------|--------|
| `get_phenotype` → circe-compiler tools | P15–P18, P22, P30 | 10–100 KB CIRCE JSON | Planned fix: accept `phenotype_id` parameter |
| `build_cohort_definition` → `compile_cohort_definition` | P31–P33 | 10–100 KB CIRCE JSON | Planned fix: `compile=True` option |
| `get_query` → `Select_Query` | P12, P29 | SQL template text | Lower priority |

---

## Tools Reference

### ohdsi-vocab (port 8001) — 11 tools
- `search_concepts`, `get_concept`, `get_concept_ancestors`, `get_concept_descendants`, `get_concept_relationships`, `preview_concept_set`
- `list_cdm_tables`, `get_table_schema`
- `search_phenotypes`, `get_phenotype`
- `search_query_patterns`, `get_query`

### circe-compiler (port 8002) — 6 tools
- `build_cohort_definition`, `compile_cohort_definition`, `validate_cohort_definition`
- `analyze_cohort_complexity`, `cohort_dry_run`, `transpile_sql_dialect`

### omcp (port 8003) — 2 tools
- `Select_Query`, `Get_Information_Schema`
