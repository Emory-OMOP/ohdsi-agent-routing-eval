# Scoring Codebook: OHDSI Agent Tool Routing Evaluation

> Deterministic scoring rules for all 33 evaluation prompts.
> Used by `score_results.py` for automated scoring and by human reviewers for manual verification.

---

## Scoring Dimensions

Each prompt is scored on two dimensions:

### 1. Tool Selection (PASS / PARTIAL / FAIL)

Based on the `tools_called` column. Rules are deterministic: check tool presence, order, and (for chains) that output IDs flow between steps.

### 2. Parameter Correctness (CORRECT / PARTIAL / INCORRECT / N/A)

Based on the `tool_arguments` column. Checks keyword relevance, concept_id sourcing, filter params, SQL correctness, and JSON passthrough.

---

## Global Rules

| Rule | Effect |
|------|--------|
| Extra exploratory tool calls | No penalty unless they introduce errors |
| Self-correction (retry after error) | PASS if final attempt succeeds |
| Max rounds reached (10) | FAIL if required tools never called |
| Correct answer without tools | FAIL for C1–C5, C8 (tools are what we evaluate) |
| Timeout (300s) | Automatic FAIL |
| Empty `tools_called` + text claims results | Flag for manual review |

---

## C1: Single Tool Selection (P01–P06)

The model must select exactly the right tool for an unambiguous request.

### P01: Find peer-reviewed cohort definitions for atrial fibrillation

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_phenotypes` called |
| **PARTIAL** | `search_phenotypes` called but preceded by unnecessary `search_concepts` |
| **FAIL** | `search_phenotypes` never called |
| **Params CORRECT** | Search term relates to "atrial fibrillation" |
| **Params INCORRECT** | Unrelated search term or no arguments |

### P02: Show me community SQL query templates for drug exposure

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_query_patterns` called |
| **PARTIAL** | `search_query_patterns` called but also calls `Select_Query` unnecessarily |
| **FAIL** | `search_query_patterns` never called |
| **Params CORRECT** | Search term relates to "drug exposure" |
| **Params INCORRECT** | Unrelated search term |

### P03: Get phenotype 77

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_phenotype` called with ID 77 |
| **PARTIAL** | `get_phenotype` called but preceded by `search_phenotypes` |
| **FAIL** | Wrong ID or `get_phenotype` never called |
| **Params CORRECT** | phenotype_id = 77 |
| **Params INCORRECT** | Any other ID |

### P04: Look up the details for OMOP concept 201826

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_concept` called with concept_id 201826 |
| **PARTIAL** | `search_concepts` used instead (indirect lookup) |
| **FAIL** | No concept tool called or hallucinated results |
| **Params CORRECT** | concept_id includes 201826 |
| **Params INCORRECT** | Wrong concept_id or missing |

### P05: What are the relationships for concept 201826?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_concept_relationships` called with concept_id 201826 |
| **PARTIAL** | `get_concept_ancestors` or `get_concept_descendants` called instead (partial relationship view) |
| **FAIL** | No relationship tool called |
| **Params CORRECT** | concept_id = 201826 |
| **Params INCORRECT** | Wrong concept_id |

### P06: Preview concept set [201826, 4193704] with descendants included

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `preview_concept_set` called with both concept_ids and `include_descendants=True` |
| **PARTIAL** | `preview_concept_set` called but missing a concept_id OR `include_descendants=False`/missing |
| **FAIL** | `preview_concept_set` not called |
| **Params CORRECT** | Both IDs present AND include_descendants=True |
| **Params PARTIAL** | Missing one ID or descendants flag |
| **Params INCORRECT** | Wrong IDs or tool not called |

---

## C2: Tool Disambiguation (P07–P10)

The model must distinguish between semantically similar tools.

### P07: What is the standard SNOMED concept for Type 2 Diabetes?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` called (not `search_phenotypes`) |
| **PARTIAL** | `search_concepts` called without standard/SNOMED filter params |
| **FAIL** | `search_phenotypes` called instead, or no tool |
| **Params CORRECT** | Search includes diabetes term + standard_only or vocabulary_id filter |
| **Params PARTIAL** | Diabetes term but no filter |
| **Params INCORRECT** | Unrelated search term |

### P08: What are the descendants of concept 201826?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_concept_descendants` called with concept_id 201826 |
| **PARTIAL** | `get_concept_relationships` called instead (broader but includes descendants) |
| **FAIL** | `search_concepts` or no hierarchy tool |
| **Params CORRECT** | concept_id = 201826 |
| **Params INCORRECT** | Wrong concept_id |

### P09: What broader categories does concept 4193704 fall under in the SNOMED hierarchy?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_concept_ancestors` called with concept_id 4193704 |
| **PARTIAL** | `get_concept_descendants` called (wrong direction) |
| **FAIL** | No hierarchy tool called |
| **Params CORRECT** | concept_id = 4193704 |
| **Params INCORRECT** | Wrong concept_id |

### P10: What columns does the measurement table have?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_table_schema` called with table "measurement" |
| **PARTIAL** | `list_cdm_tables` called (too broad) |
| **FAIL** | `Select_Query` or no tool |
| **Params CORRECT** | table_name = "measurement" |
| **Params INCORRECT** | Wrong table name |

---

## C3: Intra-Server Chaining (P11–P14)

Two or more tools from the same MCP server, called in sequence with output flowing between them.

### P11: Find a peer-reviewed cohort for Type 2 Diabetes and show me its full definition

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_phenotypes` → `get_phenotype` both called in order, phenotype ID from search results |
| **PARTIAL** | Both called but phenotype ID hardcoded (not from search output) |
| **FAIL** | Only one tool called |
| **Params CORRECT** | Search term relates to diabetes; get_phenotype ID matches a search result |
| **Params INCORRECT** | Hardcoded or hallucinated ID |

### P12: What SQL patterns exist for drug exposure, and show me the best one

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_query_patterns` → `get_query` both called in order |
| **PARTIAL** | Only `search_query_patterns` called |
| **FAIL** | Neither tool called |
| **Params CORRECT** | Search relates to drug exposure; query ID from search results |
| **Params INCORRECT** | Hallucinated query ID |

### P13: Look up concept 313217 and show me all its descendants

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_concept` → `get_concept_descendants` both called with concept_id 313217 |
| **PARTIAL** | Only `get_concept_descendants` called (skipped lookup) |
| **FAIL** | Neither tool called |
| **Params CORRECT** | concept_id = 313217 in both calls |
| **Params INCORRECT** | Wrong concept_id |

### P14: Find the standard concept for aspirin, then show me what drug ingredients it maps to

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` → `get_concept_relationships` both called, relationship ID flows from search |
| **PARTIAL** | Both called but concept_id in relationships call is hardcoded |
| **FAIL** | Chain not attempted |
| **Params CORRECT** | Search term relates to aspirin; concept_id in relationships from search results |
| **Params INCORRECT** | Hallucinated concept_id |

---

## C4: Cross-Server Chaining (P15–P20)

Tools from different MCP servers chained together.

### P15: Find a heart failure phenotype and compile it to SQL

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_phenotypes` → `get_phenotype` → `compile_cohort_definition` all 3 in order (vocab → circe) |
| **PARTIAL** | 2 of 3 tools called |
| **FAIL** | Fewer than 2 tools called |
| **Params CORRECT** | Search relates to heart failure; phenotype ID flows; CIRCE JSON passed to compile |
| **Params INCORRECT** | Chain broken or hallucinated JSON |

### P16: Validate the CIRCE JSON for phenotype 10

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_phenotype` → `validate_cohort_definition` both called (vocab → circe) |
| **PARTIAL** | Only `get_phenotype` called |
| **FAIL** | Neither called |
| **Params CORRECT** | phenotype_id = 10; CIRCE JSON from get_phenotype passed to validate |
| **Params INCORRECT** | Wrong phenotype ID or JSON not forwarded |

### P17: Get phenotype 288 and analyze how complex it is

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_phenotype` → `analyze_cohort_complexity` both called (vocab → circe) |
| **PARTIAL** | Only `get_phenotype` called |
| **FAIL** | No circe tool called |
| **Params CORRECT** | phenotype_id = 288; CIRCE JSON passed to analyze |
| **Params INCORRECT** | Wrong phenotype ID |

### P18: Preview what phenotype 519 would do without executing it

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_phenotype` → `cohort_dry_run` both called (vocab → circe) |
| **PARTIAL** | `compile_cohort_definition` called instead of `cohort_dry_run` (overshot) |
| **FAIL** | No circe tool called |
| **Params CORRECT** | phenotype_id = 519; CIRCE JSON passed to dry_run |
| **Params INCORRECT** | Wrong phenotype ID |

### P19: How many patients have Type 2 Diabetes in our database?

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` → `Select_Query` both called (vocab → omcp), concept IDs from search results used in SQL |
| **PARTIAL** | Both called but concept_id hardcoded (correct but ungrounded) |
| **FAIL** | No query or hallucinated patient counts |
| **Params CORRECT** | Diabetes search; SQL references concept_ids from search; count query |
| **Params PARTIAL** | Hardcoded concept_id in SQL |
| **Params INCORRECT** | Hallucinated IDs or wrong table |

### P20: Show me the drug_exposure table schema, then count the rows

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_table_schema` → `Select_Query` both called (vocab → omcp) |
| **PARTIAL** | Both called but SQL has errors |
| **FAIL** | Only one tool called |
| **Params CORRECT** | table = "drug_exposure"; SQL is valid COUNT query |
| **Params INCORRECT** | Wrong table or invalid SQL |

---

## C5: Parameter Construction (P21–P24)

Tests whether the model correctly builds parameters from tool outputs and multi-step workflows.

### P21: Write a query to find all diabetes conditions using standard concepts

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` with `standard_only=True` → `Select_Query` with IDs from search |
| **FAIL** | No concept lookup OR source_value query instead of standard concept query |
| **Params CORRECT** | standard_only=True used; SQL uses concept_ids from search results |
| **Params INCORRECT** | No standard filter; hardcoded or hallucinated IDs |

### P22: Compile phenotype 519 to PostgreSQL, then transpile to DuckDB

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_phenotype` → `compile_cohort_definition(dialect=postgresql)` → `transpile_sql_dialect(source=postgresql, target=duckdb)` all 3 called with correct dialect params |
| **FAIL** | Fewer than 2 tools called |
| **Params CORRECT** | phenotype_id=519; compile dialect=postgresql; transpile source=postgresql, target=duckdb |
| **Params INCORRECT** | Wrong dialects or missing transpile |

### P23: Search for hypertension concepts, preview the set with descendants, then compile a cohort

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` → `preview_concept_set` → `compile_cohort_definition` all 3 called, concept_ids propagate |
| **FAIL** | Chain not attempted (fewer than 2 tools) |
| **Params CORRECT** | Hypertension search; concept_ids from search used in preview; CIRCE JSON to compile |
| **Params INCORRECT** | IDs don't propagate |

### P24: What are the top 10 most common conditions in our database? Use proper table schema.

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `get_table_schema` → `Select_Query` both called, SQL uses correct column names from schema |
| **FAIL** | Wrong columns or no schema lookup |
| **Params CORRECT** | Schema for condition_occurrence consulted; SQL uses condition_concept_id, GROUP BY, LIMIT 10 |
| **Params INCORRECT** | Wrong column names or no aggregation |

---

## C6: Graceful Degradation (P25–P27)

Tests error handling, empty results, and invalid inputs. **All C6 prompts require manual review** for text quality.

### P25: Get phenotype 99999

| Dimension | Criteria |
|-----------|----------|
| **PASS** | Calls `get_phenotype(99999)`, reports not found, suggests alternatives (e.g., search) |
| **PARTIAL** | Calls tool but hallucinates content for nonexistent phenotype |
| **FAIL** | No tool call |
| **Params** | N/A (error handling prompt) |

### P26: Search phenotypes for quantum computing

| Dimension | Criteria |
|-----------|----------|
| **PASS** | Calls `search_phenotypes`, reports no results found |
| **PARTIAL** | Calls tool but suggests irrelevant phenotypes |
| **FAIL** | No tool call or fabricates results |
| **Params** | N/A (error handling prompt) |

### P27: Run this query: SELECT * FROM nonexistent_table LIMIT 5

| Dimension | Criteria |
|-----------|----------|
| **PASS** | Calls `Select_Query`, explains error, suggests `list_cdm_tables` or recovery |
| **PARTIAL** | Calls tool but no recovery suggestion |
| **FAIL** | Refuses to attempt or hallucinates results |
| **Params** | N/A (error handling prompt) |

---

## C7: Multi-Faceted Composition (P28–P30)

Decompose complex questions into parallel or sequential tool calls. **All C7 prompts require manual review** for completeness.

### P28: Concept set domains and published phenotypes

| Dimension | Criteria |
|-----------|----------|
| **PASS** | Both `get_concept` (for domain info) and `search_phenotypes` called, both questions answered |
| **PARTIAL** | Only one dimension addressed |
| **FAIL** | No tools called |
| **Params CORRECT** | concept_ids 201826 and 4193704 looked up; phenotype search relates to the concepts |
| **Params INCORRECT** | Wrong concept_ids |

### P29: Community approach vs database for drug cost analysis

| Dimension | Criteria |
|-----------|----------|
| **PASS** | Both `search_query_patterns` (library) and `Select_Query` (database) called |
| **PARTIAL** | Only one source consulted |
| **FAIL** | No tools called |
| **Params CORRECT** | Search relates to drug cost; SQL queries drug_cost or drug_exposure table |
| **Params INCORRECT** | Unrelated queries |

### P30: Build CKD cohort: find concepts, check phenotypes, analyze complexity

| Dimension | Criteria |
|-----------|----------|
| **PASS** | All 3 phases: `search_concepts` + `search_phenotypes` + (`get_phenotype` → `analyze_cohort_complexity` or `cohort_dry_run`) |
| **PARTIAL** | 2 of 3 phases completed |
| **FAIL** | 1 or fewer phases |
| **Params CORRECT** | CKD/kidney disease search terms; phenotype ID from search; CIRCE JSON forwarded |
| **Params INCORRECT** | Hallucinated IDs |

---

## C8: Cohort Construction (P31–P33)

End-to-end cohort building: concept lookup followed by `build_cohort_definition`. These are the most complex prompts. All C8 prompts have Tier B gold standards.

### P31: Build a cohort of patients with their first Type 2 Diabetes diagnosis with 365 days prior observation. Look up the concept first.

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` → `build_cohort_definition` both called; concept_id from search used in cohort spec |
| **PARTIAL** | `build_cohort_definition` called but concept_id hardcoded (not from search) |
| **FAIL** | `build_cohort_definition` never called |
| **Params CORRECT** | Search relates to T2DM; spec includes condition domain with concept_id from search; first occurrence; 365-day prior observation window |
| **Params PARTIAL** | Correct concept but missing observation window or first-occurrence constraint |
| **Params INCORRECT** | Wrong concept_id or wrong domain |

**Gold standard**: 7,164 patients (concept 201826 + descendants, first occurrence, 365d prior observation)

### P32: Build a cohort of hypertension patients excluding anyone with prior chronic kidney disease. Find the concepts first.

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` called for both hypertension and CKD → `build_cohort_definition` called with inclusion concept set and exclusion criteria |
| **PARTIAL** | Cohort built but exclusion missing or wrong exclusion concept |
| **FAIL** | `build_cohort_definition` never called |
| **Params CORRECT** | HTN concept (320128 or equivalent) as primary criteria; CKD concept (46271022 or equivalent) as exclusion; both from search results |
| **Params PARTIAL** | Correct primary concept but exclusion missing or uses wrong temporal window |
| **Params INCORRECT** | Wrong concepts for either condition |

**Gold standard**: 27,257 patients (HTN concept 320128 + descendants, excluding prior CKD concept 46271022 + descendants)

### P33: Build a cohort of T2DM patients aged 18-65 who received Metformin within 365 days before diagnosis. Look up concepts first.

| Dimension | Criteria |
|-----------|----------|
| **PASS** | `search_concepts` called for T2DM and Metformin → `build_cohort_definition` called with condition primary criteria, drug correlated criteria, and demographic filter |
| **PARTIAL** | Cohort built but missing one of: age filter, drug temporal window, or correct concept |
| **FAIL** | `build_cohort_definition` never called |
| **Params CORRECT** | T2DM concept (201826 or equivalent) as primary; Metformin concept (1503297 or equivalent) as correlated criteria within 365d prior; age 18–65 demographic filter |
| **Params PARTIAL** | Correct concepts but missing age filter or wrong temporal window for drug |
| **Params INCORRECT** | Wrong concepts or fundamentally wrong cohort structure |

**Gold standard**: 1,531 patients (T2DM 201826 + descendants, Metformin 1503297 + descendants within 365d prior, age 18–65)

---

## Manual Review Triggers

The automated scorer flags results for manual review when:

1. Tool match is PARTIAL (ambiguous boundary between PASS and FAIL)
2. `tools_called` is empty but `text_response` claims factual results
3. All C6 prompts (text quality of error handling matters)
4. All C7 prompts (completeness of multi-faceted responses matters)
5. Self-correction occurred (tool called, error, retry with different params)

---

## Failure Mode Taxonomy

When a prompt scores FAIL or PARTIAL, the reviewer (automated or manual) must classify the failure mode. Multiple modes may apply.

| Code | Failure Mode | Description | Example |
|:-----|:-------------|:------------|:--------|
| `TOOL_OMISSION` | Tool omission | Required tool never called | P15: only search_phenotypes, no compile |
| `WRONG_TOOL` | Wrong tool selected | Called a semantically different tool | P09: get_concept_descendants instead of ancestors |
| `HALLUCINATION` | Hallucinated output | Fabricated data without tool call, or fabricated tool results | Invented concept IDs or patient counts |
| `PARAM_ERROR` | Parameter error | Right tool, wrong arguments | Wrong concept_id, missing filter, bad SQL |
| `CHAIN_BREAK` | Chain break | Multi-step chain started but output didn't flow to next step | P14: search_concepts called, but hardcoded ID in relationships |
| `TIMEOUT` | Timeout | 300s limit reached | Agent loop spun without converging |
| `WRONG_DIRECTION` | Wrong hierarchy direction | Ancestors vs. descendants confusion | P09: descendants called when ancestors needed |
| `OVER_BROAD` | Over-broad tool | Used a broader tool when specific one exists | P10: list_cdm_tables instead of get_table_schema |
| `INFO_OMISSION` | Information omission | Tool called correctly but response omits key information | P28: concepts looked up but domains not reported |
| `REFUSAL` | Refusal to attempt | Agent refused to call a tool that should have been called | P27: refused to execute SQL |
| `SQL_ERROR` | SQL execution error | Agent's SQL was syntactically invalid or referenced wrong schema | P24: wrong column names in SELECT |

The `failure_mode` column in scored CSVs accepts pipe-delimited codes (e.g., `CHAIN_BREAK|PARAM_ERROR`).

---

## Execution Accuracy (Tier A & Tier B)

### Tier A: SQL Execution Validity

For all prompts where `Select_Query` or `compile_cohort_definition` is called, a third scoring dimension is assessed:

**`execution_valid`** (VALID / INVALID / ERROR / N/A):
- **VALID**: SQL executed without error AND returned >= 1 row
- **INVALID**: SQL executed but returned 0 rows when results were expected
- **ERROR**: SQL failed to execute (syntax error, wrong table/column, schema issue)
- **N/A**: Prompt did not involve SQL execution

This is assessed by re-executing the agent's SQL against the evaluation database (100K Synthea patients).

**Applies to prompts**: P15, P19, P20, P21, P22, P23, P24, P27, P29, P30, P31, P32, P33

### Tier B: Gold-Standard Cohort Comparison

For a subset of prompts with well-defined expected patient sets, execution accuracy is measured via set overlap:

| Prompt | Clinical Question | Gold Standard | Reference Count | Metric |
|--------|------------------|---------------|-----------------|--------|
| P15 | Heart failure phenotype → SQL | CIRCE-compiled SQL for phenotype | 2,474 | Jaccard, F1 |
| P19 | T2DM patient count | T2DM concept set (201826) + descendants | 7,167 | Jaccard, F1 |
| P21 | Diabetes conditions using standard concepts | Same T2DM concept set, standard_only | 7,167 | Jaccard, F1 |
| P24 | Top 10 most common conditions | GROUP BY concept_id ORDER BY count DESC LIMIT 10 | 10 | Jaccard, F1 |
| P31 | First T2DM diagnosis, 365d prior observation | T2DM (201826) + descendants, first occurrence, 365d obs | 7,164 | Jaccard, F1 |
| P32 | HTN excluding prior CKD | HTN (320128) + descendants, exclude CKD (46271022) + descendants | 27,257 | Jaccard, F1 |
| P33 | T2DM + Metformin within 365d, age 18–65 | T2DM (201826) + Metformin (1503297) + descendants, age filter | 1,531 | Jaccard, F1 |

Gold-standard patient sets are pre-computed against the 100K Synthea database and stored as JSON reference files in `gold_standard_references/`. The scorer compares agent-produced patient sets against these references. See `gold_standards.py` for reference SQL and the gold standard development methodology section in `METHODS_MULTI_MODEL_EVALUATION.md`.

---

## Inter-Rater Reliability Protocol

- Automated scorer handles ~90% of scores deterministically
- 10% stratified sample (by category and model) selected for manual second-scoring
- All C6 and C7 prompts always manually reviewed
- Target: Cohen's kappa >= 0.80
