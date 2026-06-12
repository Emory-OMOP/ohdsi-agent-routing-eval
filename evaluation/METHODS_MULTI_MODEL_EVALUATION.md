# Methods: Multi-Model Tool Routing Evaluation for an MCP-Native OHDSI Agent

> Working draft for JAMIA submission.

---

## Aims

Large language models are increasingly deployed as natural language interfaces to clinical databases, yet their ability to accurately extract data from standardized clinical data models through structured tool use remains poorly characterized. The OMOP Common Data Model provides a shared schema adopted by over 400 institutions worldwide [4], making it a compelling target for LLM-mediated data access — but only if the LLM can reliably select the correct tools, construct valid parameters, and produce structurally sound, verifiable output. Errors in this pipeline carry clinical research risk: incorrect cohort definitions affect study validity, wrong patient counts distort prevalence estimates, and fabricated results bypass the verification mechanisms that tool-mediated access is designed to provide.

We designed a multi-server Model Context Protocol (MCP) architecture that separates vocabulary reference, cohort compilation, and clinical data query into independent tool servers, reflecting the OHDSI ecosystem's own separation of concerns. This architecture is inherently portable: any site with an OMOP CDM instance can connect the same MCP servers to their local database without modifying the tool surface, system prompt, or evaluation harness. The evaluation therefore tests not only whether LLMs can use these tools correctly, but whether the architecture itself provides a generalizable, site-independent framework for LLM-mediated OMOP data access.

This study addresses four aims:

**Aim 1: Evaluate the accuracy of LLM tool routing for OMOP CDM data extraction across a structured capability taxonomy.**

We assess whether LLMs can correctly select, parameterize, and sequence tool calls across 19 tools spanning three MCP servers, using 33 clinically grounded prompts organized into eight capability categories of increasing complexity (single tool selection → tool disambiguation → intra-server chaining → cross-server chaining → parameter construction → graceful degradation → multi-faceted composition). Accuracy is measured at three levels: tool selection correctness (PASS/PARTIAL/FAIL), parameter fidelity (CORRECT/PARTIAL/INCORRECT), and clinical execution validity (SQL execution against the database with gold-standard cohort comparison using Jaccard index and F1 [26, 27]). This tiered evaluation — from routing mechanics through to verifiable clinical output — addresses the gap identified by Livingston et al. [32] between surface-level correctness and the downstream clinical risk of applying LLM-generated results.

**Aim 2: Determine the extent to which locally-deployed open-weight models can match cloud API models on tool routing for clinical data extraction.**

The practical value of LLM-mediated OMOP access depends on whether institutions can deploy it on-premises without relying on external API providers — a requirement driven by data governance, cost, and latency constraints. We compare 7 locally-deployed open-weight models (7B–14B parameters, running on consumer Apple Silicon hardware via Ollama) against 9 cloud API models (Claude, GPT-4.1, Gemini, DeepSeek) across the full capability taxonomy, testing whether the performance gap is uniform or concentrated in specific capability dimensions (e.g., cross-server chaining, parameter construction).

**Aim 3: Quantify the effect of sampling temperature on tool routing reliability and characterize stochasticity across models.**

Most tool-use benchmarks fix temperature at a single near-deterministic value [9], leaving the relationship between sampling stochasticity and routing accuracy unexplored. Following MI-CLEAR-LLM requirements for explicit stochasticity reporting [16], we treat temperature as an independent experimental variable at four levels (0.0, 0.3, 0.7, 1.0) with 3–5 runs per level, yielding 540 evaluations per model. We measure temperature sensitivity (accuracy delta between 0.0 and 1.0), trajectory diversity (unique tool-call sequences per prompt), and identify optimal temperature settings for tool routing — a practical deployment parameter that institutions must choose.

**Aim 4: Assess the clinical risk profile of tool routing errors using an adapted harm severity classification.**

Beyond accuracy metrics, we characterize the clinical risk of routing failures using a harm classification adapted from the AHRQ-based severity framework of Livingston et al. [32]. In our context, the LLM does not provide clinical advice directly; rather, it extracts data from the CDM through tool calls. Errors therefore carry research-operational risk rather than direct patient risk, but the severity varies:

| Risk Level | Failure Mode | Example | Downstream Impact |
|:-----------|:-------------|:--------|:------------------|
| **No harm** | Tool omission on information-only query | Fails to look up concept metadata | Researcher repeats query manually |
| **Mild** | Over-broad tool or parameter imprecision | Uses `list_cdm_tables` instead of `get_table_schema` | Correct but inefficient; extra researcher effort |
| **Moderate** | Chain break or wrong parameters in SQL | SQL runs but returns wrong columns or incomplete filter | Study results may be subtly incorrect if not caught by downstream validation |
| **Severe** | Hallucination or fabricated data without tool call | Agent claims "4,200 patients have T2DM" without querying database | Unverifiable output bypasses the tool-mediated audit trail entirely; research decisions based on fabricated evidence |
| **Critical** | Wrong cohort definition compiled and executed | Incorrect concept set or missing descendant inclusion yields wrong patient set | Directly affects cohort membership for clinical research; may propagate through multi-site studies using the same phenotype definition |

We report the distribution of failure modes (11-category taxonomy) mapped to these risk levels per model and capability category, enabling institutions to assess not just *how often* a model fails but *how dangerous* its failures are. The deterministic CIRCE compiler is notable in this analysis: because cohort SQL is generated by the compiler rather than the LLM, an entire class of structural errors (invalid SQL syntax, wrong schema references) is architecturally eliminated, isolating the LLM's failure modes to semantic concept selection and parameter construction — a safety property of the MCP multi-server design.

---

## System Architecture

### Multi-Server MCP Design

We implemented a three-server Model Context Protocol (MCP) architecture for observational health data research using the OMOP Common Data Model (CDM). The MCP specification [1] defines a standardized interface between LLM clients and tool-providing servers, enabling modular, independently versioned tool surfaces. Each server in our architecture is an independent process exposing a distinct tool surface to a shared LLM client over HTTP:

**Table 1. Server Architecture**

| Server | Transport | Port | Tools | Domain |
|--------|-----------|------|------:|--------|
| **ohdsi-vocab** | Streamable HTTP | 8001 | 12 | Vocabulary search, concept hierarchy navigation, phenotype library, query library, CDM schema introspection, concept set preview |
| **circe-compiler** | Streamable HTTP | 8002 | 6 | CIRCE cohort definition construction and compilation to executable OMOP SQL, validation, complexity analysis, dialect transpilation |
| **omcp** | SSE | 8003 | 2 | Read-only SQL query execution against a live OMOP CDM database |

All three servers query the same DuckDB [2] instance containing a Synthea-derived [3] OMOP CDM with 100,000 synthetic patients and 7.4 million vocabulary concepts, organized across two schemas: `main_vocab` (9 vocabulary reference tables) and `main_cdm` (20 clinical data tables). The **ohdsi-vocab** and **circe-compiler** servers were built with FastMCP 2.0 (Python), using the streamable-HTTP transport introduced in MCP SDK v1.26.0. The **omcp** server (fastomop/omcp) uses the SSE transport from MCP SDK v1.6.0. A fourth MCP server (history-rag, conversation history retrieval) was available in the development environment but excluded from the evaluation scope.

The architectural separation reflects fundamentally different access requirements: vocabulary reference data (read-only, cacheable), cohort compilation logic (stateless transformation), and clinical query execution (read-only but requiring query validation). This mirrors the OHDSI ecosystem's own separation of concerns between vocabulary services, cohort building (ATLAS/CIRCE [4]), and clinical data access. From the LLM's perspective, the 20 tools from all three servers are presented as a single unified tool surface; the LLM client handles routing to the correct backend transparently based on tool name.

A key safety property of this architecture is that the circe-compiler server provides **correct-by-construction** cohort SQL. The LLM's role is limited to constructing a simplified cohort specification — specifying concept sets, inclusion criteria, temporal logic, and exclusion criteria — via the `build_cohort_definition` tool, which validates and transforms this into a CIRCE cohort definition JSON. The definition is then passed to the deterministic CIRCE compilation engine [4]. The engine, not the LLM, generates the executable SQL. This two-stage pipeline (LLM → builder → compiler) is the Python/MCP equivalent of Capr [Schuemie et al., HADES], the R-based programmatic cohort construction tool in the OHDSI ecosystem, adapted for LLM tool calling. Because the compiler enforces valid SQL syntax, correct schema references, and structurally sound join patterns by construction, the system is mathematically constrained from producing destructive database errors, invalid SQL, or schema mismatches in compiled cohort queries. The LLM can still make *semantic* errors (selecting wrong concepts, omitting inclusion criteria), but an entire class of *structural* errors is architecturally eliminated. This separation is central to the system's safety profile: it reduces the clinical risk surface from "arbitrary SQL generation" to "concept selection and parameter construction," which are verifiable against the vocabulary.

### Evaluation Database

We used Synthea v3.0.0 [3] to generate 100,000 synthetic patients representative of a United States primary care population. Synthea produces clinically realistic but fully synthetic patient records spanning conditions, medications, procedures, observations, and care encounters, with temporal progressions modeled from published clinical pathways. Synthetic data has been validated as suitable for OMOP CDM pipeline development and phenotype testing [5], with the advantage of no privacy constraints and full control over population characteristics.

The synthetic records were loaded into an OMOP CDM v5.4 database via the OHDSI ETL-Synthea pipeline [6] implemented in dbt (data build tool), producing a 15 GB DuckDB instance with 87 dbt models and 1,597 passing data quality tests. DuckDB was chosen as the analytical database engine for its embedded architecture (no server process), columnar storage optimized for analytical queries, and native SQL compatibility with OMOP CDM's query patterns [2].

At this population size, clinically meaningful conditions have sufficient prevalence for gold-standard cohort comparisons: Type 2 diabetes mellitus affects approximately 7,167 patients (~7.2%), essential hypertension affects approximately 27,257 patients (~27.3%), heart failure affects 2,474 patients (~2.5%), and the condition table contains sufficient diversity for multi-criteria cohort definitions (e.g., T2DM with Metformin and age constraints yields 1,531 patients) and top-N ranking queries.

### Tool Surface (19 Evaluated Tools)

**Table 2. Evaluated Tool Surface**

| # | Server | Tool | Description |
|--:|--------|------|-------------|
| 1 | ohdsi-vocab | `search_concepts` | Search OMOP vocabulary concepts by name, code, or keyword |
| 2 | ohdsi-vocab | `get_concept` | Look up concept details by concept_id(s) |
| 3 | ohdsi-vocab | `get_concept_ancestors` | Navigate concept hierarchy upward |
| 4 | ohdsi-vocab | `get_concept_descendants` | Navigate concept hierarchy downward |
| 5 | ohdsi-vocab | `get_concept_relationships` | Show all mapped relationships for a concept |
| 6 | ohdsi-vocab | `preview_concept_set` | Preview concept set expansion with descendants |
| 7 | ohdsi-vocab | `list_cdm_tables` | List OMOP CDM table names by category |
| 8 | ohdsi-vocab | `get_table_schema` | Show columns and types for a CDM table |
| 9 | ohdsi-vocab | `search_phenotypes` | Search peer-reviewed cohort definitions in PhenotypeLibrary [4] |
| 10 | ohdsi-vocab | `get_phenotype` | Retrieve full CIRCE JSON for a phenotype by ID |
| 11 | ohdsi-vocab | `search_query_patterns` | Search community SQL query templates from QueryLibrary |
| 12 | ohdsi-vocab | `get_query` | Retrieve a specific query template by ID |
| 13 | circe-compiler | `build_cohort_definition` | Construct a CIRCE cohort definition JSON from a simplified specification |
| 14 | circe-compiler | `compile_cohort_definition` | Compile CIRCE JSON to executable SQL for a specified dialect and schema |
| 15 | circe-compiler | `validate_cohort_definition` | Validate CIRCE JSON structure and semantics |
| 16 | circe-compiler | `analyze_cohort_complexity` | Static analysis of cohort definition complexity metrics |
| 17 | circe-compiler | `transpile_sql_dialect` | Convert compiled SQL between database dialects |
| 18 | circe-compiler | `cohort_dry_run` | Preview cohort execution plan without running against database |
| 19 | omcp | `Select_Query` | Execute read-only SQL against the OMOP CDM database |

A 20th tool (`Get_Information_Schema`) was available but excluded from evaluation due to functional overlap with `get_table_schema`. All 19 evaluated tools are tested by at least one evaluation prompt.

### LLM Client and Routing Context

We evaluated tool routing through an automated webapp client: a FastAPI application that connects to all three MCP servers at startup, discovers available tools via `list_tools()`, and exposes a streaming Server-Sent Events (SSE) endpoint (`/api/chat`). The webapp implements an agentic tool-use loop following the ReAct paradigm [7]: the LLM proposes tool calls, the webapp executes them against the appropriate MCP server, and returns results to the LLM until no further tool calls are generated or a maximum of 10 rounds is reached. The 10-round limit was chosen based on the original ReAct experiments, which found that most successful tool-use episodes resolve within 6-7 interaction steps [7]; our limit provides headroom for error recovery without permitting infinite loops.

The webapp includes a system prompt (reproduced in Appendix A) that provides:
1. Database context: schema names (`main_vocab`, `main_cdm`) with explicit table listings for each schema
2. Tool catalog: all 20 tools organized by functional category (vocabulary lookup, schema reference, query patterns, phenotype library, cohort construction & compilation, SQL execution), each with a one-line description of its purpose
3. Workflow guidance: a Circe-first workflow for cohort building (check Phenotype Library → if none, build via `build_cohort_definition` → compile → execute; direct SQL only for ad-hoc non-cohort queries), instructions to use schema-qualified table names, and directives to cite concept_ids from tool results rather than guessing

No prompt explicitly names an MCP tool in the evaluation prompts; all require the LLM to infer the correct tool(s) from the natural language intent using only the system prompt's tool catalog as routing context.

---

## Evaluation Design

### Capability Taxonomy

We designed a structured capability taxonomy to systematically evaluate tool routing across eight dimensions of increasing cognitive complexity. The taxonomy draws on prior work in tool-use complexity modeling: API-Bank's three-level hierarchy (call, retrieve+call, plan+retrieve+call) [8], BFCL's progression from simple to parallel to multi-step to agentic function calling [9], and Wang et al.'s cognitive load framework for mapping capability boundaries of tool-use agents [10].

**Table 3. Capability Categories**

| Code | Category | n | What It Tests | Servers |
|:-----|:---------|--:|:--------------|:--------|
| C1 | Single Tool Selection | 6 | Pick the correct tool from 19 for an unambiguous request | ohdsi-vocab |
| C2 | Tool Disambiguation | 4 | Distinguish semantically similar tools (e.g., ancestors vs. descendants, concepts vs. phenotypes) | ohdsi-vocab |
| C3 | Intra-Server Chaining | 4 | Execute 2+ tool chains within one MCP server, with output flowing between steps | ohdsi-vocab |
| C4 | Cross-Server Chaining | 6 | Chain tools across ohdsi-vocab / circe-compiler / omcp servers | vocab→circe, vocab→omcp |
| C5 | Parameter Construction | 4 | Build tool parameters from prior tool outputs in multi-step workflows | All servers |
| C6 | Graceful Degradation | 3 | Handle errors, empty results, and invalid inputs appropriately | ohdsi-vocab, omcp |
| C7 | Multi-Faceted Composition | 3 | Decompose complex multi-part questions into parallel or sequential tool calls | All servers |
| C8 | Cohort Construction | 3 | Build novel cohort definitions by grounding concepts via vocabulary tools then constructing via `build_cohort_definition` | vocab→circe |

The taxonomy follows a cumulative complexity progression: C1-C2 test tool *selection* (can the model pick the right tool?), C3-C4 test tool *orchestration* (can the model chain tools across servers?), C5 tests *parameter fidelity* (do outputs correctly propagate as inputs?), C6 tests *robustness* (does the model degrade gracefully?), C7 tests *composition* (can the model decompose a complex question into multiple tool-use phases?), and C8 tests *construction* (can the model build novel cohort definitions through the correct-by-construction pipeline?). C8 is critical because it validates the safety architecture: without LLM-driven cohort construction → validation → compilation, the CIRCE compiler is merely a pass-through for pre-built phenotypes, not the safety guardrail claimed by the architecture. This progression is analogous to the "simple → parallel → multiple → multi-turn → agentic" hierarchy used in BFCL [9] but specialized for the multi-server architecture, where cross-server chaining (C4) represents a capability unique to MCP-native designs.

### Prompt Construction

We designed 33 natural language prompts across the eight capability categories. Prompts were authored by a domain expert in OMOP CDM analysis to reflect realistic clinical research tasks, following the recommendation of Grace et al. [11] to derive evaluation tasks from real user workflows (20-50 tasks) with domain expert involvement. No prompt explicitly names an MCP tool; all require the LLM to infer the correct tool(s) from natural language intent.

Each prompt specifies an expected tool sequence and deterministic PASS/PARTIAL/FAIL scoring rules (see Scoring). Prompts use verified reference data: phenotype IDs (77, 10, 288, 519) from the OHDSI PhenotypeLibrary [4], OMOP concept IDs (201826 for Type 2 diabetes mellitus, 4193704 for Type 2 diabetes mellitus without complication, 313217 for atrial fibrillation) confirmed present in the vocabulary, and CDM table names verified against the live database schema.

**Evolution from Phase 1.** The evaluation design underwent a major revision from an initial 24-prompt, 11-round design based on three findings: (1) two prompts tested MCP resource reading, which is not supported by the webapp agent loop, making them impossible to pass; (2) 7 of 18 tools were never tested (`get_concept`, `get_concept_ancestors`, `get_concept_relationships`, `preview_concept_set`, `analyze_cohort_complexity`, `transpile_sql_dialect`, `cohort_dry_run`); and (3) scoring criteria were subjective and not automatable. The redesign removed 9 prompts, added 15 new prompts, and restructured the remaining into a multi-category taxonomy to achieve complete tool coverage and deterministic scoring. A subsequent Phase 3 added the C8 (Cohort Construction) category with 3 prompts testing `build_cohort_definition`, bringing the total to 33 prompts across eight categories. This iterative refinement follows the approach recommended by Grace et al. [11] of treating evaluation as a living artifact that evolves with observed failure patterns.

### Model Selection

We selected 16 models spanning five provider ecosystems to evaluate routing capability across model size, architecture, and inference locality (on-premises vs. cloud API):

**Table 4. Models Evaluated**

| # | Provider | Model ID | Parameters | Context | Specialization | Inference |
|--:|:---------|:---------|:-----------|:--------|:---------------|:----------|
| 1 | Ollama | `qwen3:8b` | 8B | 32K | General | Local |
| 2 | Ollama | `qwen3:8b-16k` | 8B | 16K | General | Local |
| 3 | Ollama | `qwen3:14b` | 14B | 32K | General | Local |
| 4 | Ollama | `qwen3-coder:latest` | 8B | 32K | Code generation | Local |
| 5 | Ollama | `llama3.1:8b` | 8B | 128K | General | Local |
| 6 | Ollama | `mistral:7b` | 7B | 32K | General | Local |
| 7 | Ollama | `granite3.1-dense:8b` | 8B | 128K | Enterprise | Local |
| 8 | Claude API | `claude-sonnet-4-20250514` | — | 200K | General (balanced) | Cloud |
| 9 | Claude API | `claude-haiku-4-5-20251001` | — | 200K | General (fastest) | Cloud |
| 10 | Claude API | `claude-opus-4-6` | — | 200K | General (most capable) | Cloud |
| 11 | OpenAI API | `gpt-4.1` | — | 1M | General | Cloud |
| 12 | OpenAI API | `gpt-4.1-mini` | — | 1M | General (efficient) | Cloud |
| 13 | Gemini API | `gemini-2.5-pro` | — | 1M | General | Cloud |
| 14 | Gemini API | `gemini-2.5-flash` | — | 1M | General (fast) | Cloud |
| 15 | DeepSeek API | `deepseek-chat` (V3) | 671B MoE | 128K | General | Cloud |
| 16 | DeepSeek API | `deepseek-reasoner` (R1) | 671B MoE | 128K | Reasoning | Cloud |

**Model selection rationale.** The local models were chosen to test three axes relevant to institutional deployment: (a) parameter count (7B → 14B), representing the range deployable on consumer/workstation hardware; (b) architecture diversity (Qwen3, LLaMA 3.1, Mistral, Granite), capturing differences in tool-use training approaches; and (c) specialization (general vs. code-optimized). The cloud API models represent current state-of-the-art tool-use capabilities across major providers and serve as a performance ceiling for comparison with local models. All local models ran on Apple Silicon (M-series) hardware, reflecting a realistic on-premises deployment where an institution runs both the LLM and MCP servers without external API dependencies.

**Excluded models.** Phi-4 14B (Microsoft) was excluded because `phi4:14b` in Ollama does not support structured tool calling — a prerequisite for our evaluation, which requires the model to emit tool call JSON rather than free-text descriptions of tool invocations. Community-maintained variants with tool templates exist but were not used to ensure reproducibility with official model releases. MedGemma 4B and 27B (Google) were similarly excluded for lacking structured tool calling support. Moonshot-v1-32K (Kimi) was excluded due to persistent API connectivity issues during the evaluation period. Results from excluded models are archived separately.

### Temperature as Experimental Variable

Unlike most tool-use benchmarks, which fix temperature at a single near-deterministic value (BFCL uses temperature=0.001 [9]; ToolBench uses greedy decoding [13]), we treat temperature as an independent experimental variable crossed with model and prompt. This design is motivated by three findings from the literature:

1. **Temperature affects tool-use accuracy.** Analysis of BFCL results shows accuracy can vary up to 10 percentage points between temperature=0.0 and temperature=0.7 on certain function-calling categories [14].
2. **Even temperature=0 is not deterministic.** Braylan and Lease [15] demonstrated that LLMs are not fully reproducible even at temperature=0 with fixed seeds, due to API routing, floating-point non-determinism, and hardware-level variance. They recommend prediction intervals rather than confidence intervals, and find that 3-4 runs suffice at temperature=0 for interval width < 0.01.
3. **MI-CLEAR-LLM guidelines require stochasticity reporting.** The Minimum Reporting Items for Clear Evaluation of Accuracy Reports of LLMs in Healthcare (MI-CLEAR-LLM) [16] identifies stochasticity management as a required reporting item, noting that only 15.1% of published LLM studies in leading medical journals adequately reported stochasticity parameters [17].

**Table 5. Temperature × Runs Design**

| Temperature | Runs per model-prompt | Rationale |
|:------------|:---------------------|:----------|
| 0.0 | 3 | Near-deterministic; 3-4 runs sufficient per Braylan & Lease [15] |
| 0.3 | 5 | Low stochasticity; captures variance in near-deterministic regime |
| 0.7 | 5 | Moderate; region where largest variance observed in BFCL analysis [14] |
| 1.0 | 5 | High stochasticity; upper bound of standard range |

Per model: 33 prompts × (3 + 5 + 5 + 5 runs) = **594 evaluations**.
16 models × 594 = **9,504 total evaluations**.

The four temperature values span the range used in systematic temperature studies in healthcare LLM evaluation: 0.0-1.0 in clinical task evaluation [18], 0.0-1.0 in 0.25 increments for emergency medicine diagnostics [19], and 0.1-1.9 in 0.3 increments in the "Hot or Cold?" study across 12 models [20]. Our values {0.0, 0.3, 0.7, 1.0} sample the key inflection points while keeping the total evaluation count tractable.

### Automated Evaluation Harness

The automated harness (`run_evaluation.py`) executes all model-prompt-temperature combinations:

1. **Authenticates** with the webapp via passkey → JWT token exchange.
2. **Iterates** through all 33 prompts sequentially, sending each to the `/api/chat` SSE endpoint with provider, model, and temperature specified per request.
3. **Creates a fresh session** for each prompt (no `session_id` passed), isolating evaluation to single-turn routing. Single-turn isolation was chosen because multi-turn conversation degrades LLM performance by an average of 39% compared to single-turn [21], confounding the measurement of tool routing capability with context management capability. Each prompt is evaluated independently.
4. **Streams and parses** the SSE response, extracting structured data from six event types: `tool_call` (tool name and arguments), `tool_result` (tool name and execution result, truncated to 2,000 characters), `text` (LLM natural language response), `done` (agent loop round count), `error` (error events), and `session` (webapp session identifier). The `tool_result` events are critical for guided-condition scoring, where execution results from `compile_cohort_definition` are parsed directly rather than re-executed.
5. **Measures wall-clock latency** from request initiation to stream completion, with a 300-second timeout per prompt.
6. **Writes results** to a per-run CSV file organized as `results/<creator>/<model>/<timestamp>.csv`, with columns for prompt metadata, tool call data, scoring fields (populated by `score_results.py`), latency, rounds, temperature, and run identifier.
7. **Logs provenance** (model, provider, git commit SHA, timestamp, prompts completed) to a central `result_provenance.csv` for audit trail.

The harness supports subset execution (`--prompts 17,18`) for targeted smoke testing and configurable inter-prompt delay (`--delay 5`) for rate-limited API providers.

---

## Scoring

### Scoring Codebook

Each of the 33 prompts has deterministic scoring rules documented in both human-readable form (`SCORING_CODEBOOK.md`) and as executable Python code (`codebook.py`). Scoring operates on two primary dimensions:

**Dimension 1: Tool Selection** (PASS / PARTIAL / FAIL)
- **PASS**: Required tool(s) called in expected order with output flowing between steps.
- **PARTIAL**: Correct intent but suboptimal path (e.g., unnecessary intermediate calls, hardcoded IDs instead of tool-derived IDs, broader tool when a more specific one exists).
- **FAIL**: Wrong tool, no tool call, hallucinated results, or timeout (300s).

The ternary scoring scheme (PASS/PARTIAL/FAIL) was chosen over binary (correct/incorrect) based on the rubric design methodology of Sharma et al. [22], which demonstrated that ternary rubrics capture meaningful distinctions in agent behavior that binary scoring collapses — particularly the difference between "correct intent, suboptimal execution" (PARTIAL) and "fundamentally wrong approach" (FAIL).

**Dimension 2: Parameter Correctness** (CORRECT / PARTIAL / INCORRECT / N/A)
- **CORRECT**: Search terms match prompt intent, concept IDs sourced from prior tool output, filter parameters applied appropriately, SQL uses correct column names.
- **PARTIAL**: Right tool but imprecise parameters (e.g., overly broad search term).
- **INCORRECT**: Wrong concept IDs, hallucinated parameters, invalid SQL.
- **N/A**: Error handling prompts (C6) where parameter correctness is not applicable.

**Default parameter handling.** When a tool defines a parameter with a default value (e.g., `search_concepts(standard_only: bool = True)`), we treat the model's omission of that parameter as equivalent to supplying the default value. This follows the consensus of major tool-use benchmarks: BFCL explicitly treats omission of truly optional parameters as correct [9], ComplexFuncBench demonstrates execution equivalence — `Search_Hotel(New_York, adults=1)` and `Search_Hotel(New_York)` are scored identically when the default for `adults` is 1 [23] — and execution-based benchmarks (ToolBench [13], API-Bank [8]) implicitly accept default-reliant calls through outcome comparison. We document this policy explicitly following MI-CLEAR-LLM's requirement for transparent evaluation methodology [16].

### Automated Scorer

The automated scorer (`score_results.py`) reads result CSVs and applies codebook rules:

1. Parses `tools_called` (pipe-delimited) and `tool_arguments` (JSON) columns from each row.
2. Applies the prompt-specific rule from `codebook.py`, which checks tool presence, ordering, and argument values.
3. Fills `result`, `parameters_correct`, and `failure_mode` columns. Existing manual scores are preserved (not overwritten).
4. Flags rows for manual review when:
   - The tool match is PARTIAL (ambiguous boundary between correct and suboptimal)
   - `tools_called` is empty but `text_response` claims factual results (potential hallucination)
   - All C6 prompts (text quality of error handling is not captured by tool selection scoring)
   - All C7 prompts (completeness of multi-faceted responses requires human judgment)
   - Self-correction occurred (tool called, error, retry)

### Global Scoring Rules

| Rule | Effect | Justification |
|------|--------|---------------|
| Extra exploratory tool calls | No penalty unless they introduce errors | Penalizing exploration would discourage legitimate information-gathering strategies |
| Self-correction (retry after error) | PASS if final attempt succeeds | Aligns with ReAct's iterative refinement design [7] |
| Max rounds reached (10) | FAIL if required tools never called | Agent failed to converge within the allocated interaction budget |
| Correct answer without tools | FAIL for C1-C5 | Tool routing is the measured capability; correct answers via memorization bypass the construct under evaluation |
| Timeout (300s) | Automatic FAIL | Conservative limit; 99th percentile latency in pilot runs was <120s |
| Default parameter omission | Treated as supplying the default value | Per BFCL [9] and ComplexFuncBench [23] consensus |

### Failure Mode Taxonomy

When a prompt scores FAIL or PARTIAL, the automated scorer classifies the failure into one or more standardized categories. The taxonomy draws on Winston and Just's taxonomy of failures in tool-augmented LLMs [24] and Cemri et al.'s MAST taxonomy for multi-agent systems [25]:

**Table 6. Failure Mode Taxonomy**

| Code | Mode | Description |
|:-----|:-----|:------------|
| TOOL_OMISSION | Tool omission | Required tool never called |
| WRONG_TOOL | Wrong tool | Called a semantically different tool |
| HALLUCINATION | Hallucination | Fabricated data without tool call or fabricated tool results |
| PARAM_ERROR | Parameter error | Right tool, wrong arguments |
| CHAIN_BREAK | Chain break | Multi-step chain started but output didn't flow to next step |
| TIMEOUT | Timeout | 300s limit reached |
| WRONG_DIRECTION | Wrong direction | Ancestors/descendants confusion (hierarchy traversal error) |
| OVER_BROAD | Over-broad tool | Used a broader tool when a more specific one exists |
| INFO_OMISSION | Information omission | Tool called correctly but response omits key information |
| REFUSAL | Refusal | Agent refused to call a tool that should have been called |
| SQL_ERROR | SQL error | Agent's SQL was syntactically invalid or referenced wrong schema |

The `failure_mode` column in scored CSVs accepts pipe-delimited codes. Failure mode distribution is reported per model and per category to identify systematic patterns (e.g., whether smaller models disproportionately hallucinate while larger models more commonly over-broaden). The correct-by-construction property of the circe-compiler (see System Architecture) is directly observable in the failure mode distribution: for CIRCE-compiled queries, SQL_ERROR should never occur, and the LLM's remaining failure modes are constrained to semantic concept selection (PARAM_ERROR, WRONG_TOOL) and chain orchestration (CHAIN_BREAK, TOOL_OMISSION). This prediction is itself a testable hypothesis of the multi-server architecture.

### Execution Accuracy (Tiered)

Tool routing correctness alone does not guarantee clinically useful output. To bridge this gap, we assess execution accuracy at two tiers, following Gemini reviewer recommendations for clinical execution validation:

**Tier A — SQL Execution Validity** (13 SQL-generating prompts: P15, P19-P24, P27, P29-P33):

We re-execute the agent's SQL against the evaluation database and classify the result:
- **VALID**: SQL executed without error AND returned ≥ 1 row
- **INVALID**: SQL executed but returned 0 rows when results were expected
- **ERROR**: SQL failed (syntax error, wrong table/column, schema mismatch)

This catches failure modes that tool routing scoring misses: an agent that calls `Select_Query` with hallucinated column names scores PASS on tool selection but ERROR on execution validity.

**Tier B — Gold-Standard Cohort Comparison** (7 prompts with well-defined expected patient sets):

We compute set overlap between the agent's query results and pre-computed gold-standard reference cohorts using Jaccard index and patient-level F1 — the standard metrics for phenotype algorithm validation in OHDSI [26, 27]:

**Table 7. Gold-Standard Comparisons**

| Prompt | Category | Clinical Question | Reference Cohort | n | Metrics |
|--------|----------|------------------|-----------------|--:|---------|
| P15 | C4 | Heart failure phenotype → SQL | HF concept 316139 + descendants in condition_occurrence | 2,474 | Jaccard, F1 |
| P19 | C5 | T2DM patient count | T2DM concept 201826 + descendants in condition_occurrence | 7,167 | Jaccard, F1 |
| P21 | C5 | Diabetes conditions, standard concepts | T2DM concept set with standard_only filter | 7,167 | Jaccard, F1 |
| P24 | C7 | Top 10 most common conditions | GROUP BY condition_concept_id ORDER BY COUNT DESC LIMIT 10 | 10 | Rank overlap@10 |
| P31 | C8 | First T2DM dx with 365d prior observation | T2DM first occurrence + observation_period ≥365 days | 7,164 | Jaccard, F1 |
| P32 | C8 | Hypertension excluding prior CKD | HTN concept 320128 + descendants, anti-join on CKD 46271022 | 27,257 | Jaccard, F1 |
| P33 | C8 | T2DM aged 18-65 with prior Metformin | T2DM + age 18-65 + Metformin 1503297 within 365d before dx | 1,531 | Jaccard, F1 |

**Gold standard development methodology.** Reference cohorts were constructed by the study author (a domain expert in OMOP CDM analysis) using hand-written SQL queries that implement the clinical logic described in each evaluation prompt. The development process followed three principles:

1. **Concept set construction via vocabulary hierarchy.** Each clinical concept (Type 2 diabetes mellitus, essential hypertension, chronic kidney disease, Metformin) is defined as a standard OMOP concept plus all its descendants in the concept_ancestor hierarchy. This mirrors the concept set expansion approach used throughout OHDSI tooling (ATLAS, Capr, PhenotypeLibrary) [4] and ensures that the reference captures all granular descendant codes (e.g., "Type 2 diabetes mellitus without complication" under the T2DM ancestor). Anchor concept IDs — T2DM (201826), essential hypertension (320128), chronic kidney disease (46271022), Metformin (1503297), heart failure (316139) — were selected as the canonical standard concepts for each condition/drug in the OMOP vocabulary.

2. **Literal interpretation of prompt language.** Each gold standard implements the clinical criteria stated in the evaluation prompt as directly as possible, without adding unstated clinical refinements. For example, P31 ("first Type 2 Diabetes diagnosis with 365 days prior observation") is implemented as a correlated subquery identifying each patient's earliest T2DM condition_occurrence record, joined to observation_period to verify ≥365 days of prior observation. P32 ("hypertension patients excluding anyone with prior chronic kidney disease") uses a temporal anti-join — CKD records must precede the hypertension record. P33 ("T2DM patients aged 18-65 who received Metformin within 365 days before diagnosis") combines a three-way join across condition_occurrence, person, and drug_exposure with age and temporal window constraints.

3. **Validation against Synthea population characteristics.** Reference set sizes were verified for clinical plausibility given the 100,000-patient Synthea population: T2DM prevalence (~7.2%), hypertension prevalence (~27%), and the progressive filtering effect of additional criteria (P31 loses 3 patients from P19 due to the observation window; P33 narrows to 1,531 from T2DM's 7,167 by adding age + Metformin constraints).

The gold standards are intentionally *lenient* reference definitions rather than fully specified phenotype algorithms. Production OHDSI phenotypes typically include additional criteria (era collapsing, washout periods, index date logic) that the evaluation prompts do not specify. Because the prompts test whether the model can construct *any* reasonable cohort matching the stated criteria — not whether it produces a publication-ready phenotype — the reference queries implement only what the prompt asks for. Tier B scores therefore measure alignment between the agent's interpretation and the prompt's literal clinical logic, with Jaccard and F1 tolerating partial overlap rather than requiring exact match.

**Two-condition scoring paths.** Gold standard comparison operates differently under the two experimental conditions:

- **Open condition**: The scorer extracts SQL from the agent's `Select_Query` tool arguments, re-executes it against the evaluation database, and computes set overlap metrics against the reference.
- **Guided condition**: The agent uses `build_cohort_definition` → `compile_cohort_definition(execute=True)`, which returns execution results directly in the tool response. The scorer parses person_ids from the `compile_cohort_definition` tool result JSON — no SQL re-execution is needed because the results are already computed by the deterministic CIRCE pipeline. If no `compile_cohort_definition` result is found, the scorer falls back to the open-condition path (extracting SQL from `Select_Query`) to handle models that may use raw SQL even in the guided condition.

Gold-standard reference sets are pre-computed against the evaluation database and stored as JSON files (`gold_standard_references/P{id}_reference.json`). Reference generation is deterministic and reproducible via `gold_standards.py generate --db <path>`.

### Inter-Rater Reliability

The automated scorer handles approximately 90% of scores deterministically. A 10% stratified sample (stratified by category and model) is selected for manual second-scoring by a human reviewer. All C6 and C7 prompts are always manually reviewed (text quality and completeness matter beyond tool selection). Target: Cohen's kappa ≥ 0.80 between automated and manual scores.

---

## Outcome Measures

### Primary Outcomes

1. **Tool routing accuracy per model per temperature**: Mean PASS rate with 95% Bayesian Beta-Binomial credible intervals (uniform Beta(1,1) prior). We use Bayesian credible intervals rather than frequentist confidence intervals following Bowyer et al. [28], who demonstrated that CLT-based confidence intervals dramatically underestimate uncertainty in LLM evaluations with fewer than a few hundred datapoints.

2. **Cross-server chain completion**: PASS rate on C4 prompts (6 prompts testing chains across ohdsi-vocab → circe-compiler and ohdsi-vocab → omcp). This is the critical capability differentiating multi-server MCP architectures from monolithic tool designs.

3. **Temperature sensitivity**: Accuracy delta between temperature=0.0 and temperature=1.0 per model, quantifying each model's robustness to sampling stochasticity in the tool routing domain.

### Secondary Outcomes

4. **PASS+PARTIAL rate**: Combined proportion reflecting correct intent regardless of path optimality.
5. **Parameter correctness rate**: Proportion of tool calls with semantically valid arguments.
6. **Execution validity rate**: Proportion of SQL-generating prompts where the agent's SQL executed successfully (Tier A).
7. **Gold-standard cohort accuracy**: Mean Jaccard index and F1 for Tier B prompts, measuring whether correct routing produces clinically correct output.
8. **Failure mode distribution**: Frequency of each failure type per model and category.
9. **Category difficulty ranking**: Ordered by aggregate PASS rate across all models, identifying which capability dimensions are hardest.
10. **Trajectory diversity**: Number of unique tool-call sequences observed per prompt-model-temperature combination. High trajectory diversity at a given temperature indicates that the model explores multiple valid (or invalid) routing paths, while low diversity indicates deterministic behavior. This metric addresses MI-CLEAR-LLM's requirement for reporting "consistency assessment across attempts" [16].
11. **Latency**: Wall-clock time per prompt (mean, median, min, max), stratified by provider, model, and temperature.
12. **Agent loop depth**: Number of LLM-tool interaction rounds per prompt, as a measure of routing efficiency.

---

## Statistical Analysis Plan

### Confidence Intervals

All proportions (pass rates) are reported with 95% Bayesian Beta-Binomial credible intervals using a uniform Beta(1,1) prior. With 18 runs per prompt-model combination (3 at temp=0.0 + 5 each at 0.3, 0.7, 1.0), the effective sample size per model at each temperature point provides narrow-enough intervals for meaningful comparison. We use exact Beta quantiles via `scipy.stats.beta`, falling back to a normal approximation when scipy is unavailable. The Bayesian approach is recommended by Bowyer et al. [28] specifically for LLM evaluations where sample sizes are typically in the tens to low hundreds.

### Temperature Effects

- **Within-model temperature analysis**: For each model, we test whether pass rate varies significantly across the four temperature levels using Cochran's Q test (binary: PASS vs. not-PASS across repeated measures at different temperatures).
- **Temperature-stratified tables**: All primary tables are reported both overall and stratified by temperature, enabling readers to assess whether reported accuracies are sensitive to this hyperparameter.
- **Optimal temperature identification**: For each model, we report the temperature yielding the highest mean pass rate. This addresses a practical deployment question: should institutions fix temperature at 0 for tool routing tasks, or does moderate stochasticity improve exploration?

### Comparative Tests

- **Fisher's exact test**: Pairwise model comparison per prompt, testing whether pass rates differ significantly between model pairs.
- **Friedman test**: Non-parametric repeated-measures test across capability categories, asking whether category difficulty varies systematically across models.
- **Jonckheere-Terpstra trend test**: For local models ordered by parameter count (7B → 8B → 14B), testing whether larger models route more accurately — the key question for institutional deployment decisions.

### Multiple Comparisons

Bonferroni correction is applied to pairwise Fisher tests. With 16 models, there are 120 model pairs; individual comparisons are reported at α = 0.05/120 ≈ 0.00042.

---

## MI-CLEAR-LLM Compliance

We report compliance with the Minimum Reporting Items for Clear Evaluation of Accuracy Reports of Large Language Models in Healthcare (MI-CLEAR-LLM) [16], a 6-item checklist developed to standardize LLM evaluation reporting in medical journals. A 2025 adherence study found that only 15.1% (24/159) of published LLM studies in leading medical journals adequately reported stochasticity management [17], motivating explicit compliance documentation.

**Table 8. MI-CLEAR-LLM Compliance**

| # | Item | Status | Implementation |
|--:|:-----|:-------|:---------------|
| 1 | LLM identification | Compliant | Model name, version, provider, parameter count, and context window documented per model (Table 4). Query dates recorded in result CSV timestamps. |
| 2 | Stochasticity management | Compliant | Four temperature levels × 3–5 runs each (Table 5), yielding **n=18 stochastic repetitions per prompt-model pair** (≥20 when aggregated across adjacent temperature levels) and **540 evaluations per model**. Bayesian Beta-Binomial credible intervals [28] computed across runs. Trajectory diversity (unique tool-call sequences) reported as consistency metric per prompt-model-temperature. Synthesis methodology: majority-vote result and mean pass rate reported per cell. |
| 3 | Prompt wording | Compliant | All 33 prompts published verbatim in `routing_test_results.csv`. System prompt reproduced in full in Appendix A. |
| 4 | Prompt structuring | Compliant | Single-turn isolation with fresh session per prompt. System prompt structure documented in Section "LLM Client and Routing Context." |
| 5 | Prompt testing/optimization | Compliant | Phase 1 → Phase 2 evolution documented, including specific failures that motivated redesign (resource reading incompatibility, incomplete tool coverage, non-automatable scoring). |
| 6 | Test data independence | Compliant | Evaluation database generated by Synthea v3.0.0 [3], producing fully synthetic patient records not present in any model's training corpus. The Synthea generation was not seeded; the specific dataset used for evaluation is archived as a static artifact on Zenodo [34] with SHA-256 checksums, ensuring gold-standard reference cohorts are stable and verifiable. Vocabulary data (OMOP CDM v5.4, Athena release v5.0 27-FEB-25) is publicly available but concepts are identified by numeric IDs requiring tool-mediated lookup, not memorizable from training data. |

---

## Reproducibility

All evaluation materials are publicly available in the project repository:

**Table 9. Reproducibility Artifacts**

| Component | Path |
|-----------|------|
| 30 evaluation prompts | `publications/jamia/plan_and_results/routing_test_results.csv` |
| Scoring codebook (human-readable) | `publications/jamia/plan_and_results/SCORING_CODEBOOK.md` |
| Scoring codebook (executable) | `publications/jamia/plan_and_results/codebook.py` |
| Scoring helpers + failure taxonomy | `publications/jamia/plan_and_results/scorers.py` |
| Automated scorer | `publications/jamia/plan_and_results/score_results.py` |
| Gold-standard execution scorer | `publications/jamia/plan_and_results/gold_standards.py` |
| Gold-standard reference sets | `publications/jamia/plan_and_results/gold_standard_references/` |
| Evaluation harness | `publications/jamia/plan_and_results/run_evaluation.py` |
| Analysis script | `publications/jamia/plan_and_results/analyze_results.py` |
| Results (per-model CSVs) | `publications/jamia/plan_and_results/results/` |
| System prompt | `webapp/backend/config.py` (lines 50-96) |
| Evaluation database (Synthea CSVs, vocabulary manifest, gold standards, config) | Zenodo: DOI [10.5281/zenodo.18726343](https://doi.org/10.5281/zenodo.18726343) [34] |

The Synthea patient generation was not seeded (`-s` flag was not used), so re-running `./run_synthea -p 100000 Georgia` will produce a different patient population. The specific dataset used for this evaluation is archived on Zenodo [34] with SHA-256 checksums for all artifacts. To reconstruct the evaluation database, researchers should use the archived Synthea CSVs (not regenerate them) combined with Athena OHDSI vocabularies (v5.0 27-FEB-25) and the provided dbt ETL configuration. The evaluation harness requires only `httpx` (HTTP client) and a running webapp instance connected to all three MCP servers. Temperature, provider, model, and prompt subset are all configurable via command-line flags.

---

## Limitations

**Single evaluator.** All manual scoring and review was performed by a single human evaluator who is also the system developer, introducing potential bias. The automated scorer mitigates this for ~90% of scores, and inter-rater reliability is assessed on a stratified subsample. Future work should employ blinded multi-rater evaluation.

**Single-turn isolation.** Each prompt was evaluated in a fresh session without conversational context. Real-world usage involves multi-turn interactions where prior tool results inform subsequent routing decisions. Laban et al. [21] found a 39% average performance drop in multi-turn conversation, suggesting our single-turn results may overestimate real-world performance. Single-turn evaluation was chosen to isolate tool routing capability from context management, following Grace et al.'s recommendation to start with single-turn evaluation before scaling to multi-turn [11].

**Synthetic data.** The Synthea-derived database [3] contains 100,000 synthetic patients, sufficient for meaningful cohort overlap metrics but limited in clinical complexity. Synthea models primary care conditions (diabetes, hypertension, heart failure, CKD, asthma) but lacks oncology, clinical notes, and complex temporal relationships. PhenotypeLibrary definitions designed for real EHR data may match differently against Synthea's simplified disease model. Gold-standard Jaccard/F1 scores reflect alignment between the agent's SQL and the reference query on synthetic data, not clinical validity against a real patient population.

**Deterministic scoring trade-offs.** The automated codebook captures tool selection and parameter correctness deterministically but cannot evaluate response quality (clarity, clinical reasoning, explanation depth). C6 and C7 prompts are always manually reviewed to partially address this, but overall text quality is not systematically scored.

**Tool surface stability.** Tool descriptions, parameter schemas, and system prompt are fixed at evaluation time. Changes to tool descriptions would likely change routing behavior, particularly for smaller models sensitive to prompt phrasing.

**Local inference constraints.** Ollama models ran on consumer Apple Silicon hardware. Model performance and latency may differ on data-center GPU hardware, limiting generalizability of latency measurements. Memory pressure on larger models (14B) may also affect inference quality.

**Cross-provider temperature semantics.** Temperature parameters are not identically implemented across providers. Ollama's default temperature (0.8) differs from OpenAI's (1.0) and Claude's (1.0). While we explicitly set temperature for each request, the mapping from temperature value to sampling behavior may vary across implementations, introducing a source of cross-provider variance that is not controlled for.

---

## Appendix A: System Prompt

The following system prompt was used for all automated evaluations, configured in `webapp/backend/config.py`:

```
You are an OHDSI research assistant with access to OMOP vocabulary tools, a CIRCE
cohort compiler, and a SQL query tool.

## Database
DuckDB with OMOP CDM v5.4. Two schemas:
- main_vocab: concept, concept_ancestor, concept_relationship, concept_class,
  concept_synonym, vocabulary, domain, drug_strength, relationship
- main_cdm: person, condition_occurrence, drug_exposure, procedure_occurrence,
  measurement, observation, visit_occurrence, visit_detail, observation_period,
  death, note, note_nlp, specimen, device_exposure, condition_era, drug_era,
  dose_era, payer_plan_period, cost, provider, care_site, location

Always qualify tables with schema: main_vocab.concept, main_cdm.person, etc.

## Tools
Vocabulary lookup:
- search_concepts: Find concepts by name, code, or keyword. Start here.
- get_concept: Look up a single concept by concept_id.
- get_concept_ancestors: Get ancestor concepts in the hierarchy.
- get_concept_descendants: Get descendant concepts in the hierarchy.
- get_concept_relationships: Find related concepts (Maps to, Is a, etc).
- preview_concept_set: Expand a concept set with descendants.

Schema reference:
- list_cdm_tables: List available OMOP CDM tables by category.
- get_table_schema: Get column names and types for a specific table.

Query patterns:
- search_query_patterns: Search OHDSI QueryLibrary for reusable SQL templates.
- get_query: Get a specific QueryLibrary template by ID.

Phenotype library:
- search_phenotypes: Search the OHDSI Phenotype Library for cohort definitions.
- get_phenotype: Get a cohort definition JSON by cohort_id.

Cohort compilation:
- compile_cohort_definition: Compile CIRCE cohort JSON to SQL.
  Use dialect='duckdb', cdm_schema='main_cdm', vocab_schema='main_vocab'.
- validate_cohort_definition: Check a cohort definition for errors.
- analyze_cohort_complexity: Static analysis of query complexity.
- transpile_sql_dialect: Convert SQL between database dialects.
- cohort_dry_run: Preview what a cohort would do without executing.

SQL execution:
- Select_Query: Execute a read-only SELECT query against the database.
- Get_Information_Schema: View available tables and columns.

## Workflow
1. Use vocabulary tools to find concept_ids — never guess IDs.
2. For SQL queries, always use schema-qualified table names
   (main_vocab.concept, main_cdm.condition_occurrence, etc).
3. For cohorts: search phenotypes → get definition → compile →
   adapt qualified_events segment for read-only execution → run via Select_Query.
4. Always cite concept_ids and counts from tool results.
```

---

## References

[1] Anthropic. "Introducing the Model Context Protocol." November 25, 2024. https://www.anthropic.com/news/model-context-protocol — See also MCP Specification (2025-11-25 revision): https://modelcontextprotocol.io/specification/2025-11-25

[2] Raasveldt M, Muhleisen H. "DuckDB: an Embeddable Analytical Database." SIGMOD 2019 Demo. DOI: 10.1145/3299869.3320212.

[3] Walonoski J, Kramer M, Nichols J, et al. "Synthea: An approach, method, and software mechanism for generating synthetic patients and the synthetic electronic health care record." *J Am Med Inform Assoc*. 2018;25(3):230-238. DOI: 10.1093/jamia/ocx079.

[4] OHDSI. *The Book of OHDSI*. 2019. Chapters 11-12 (Cohort definitions, PhenotypeLibrary). https://ohdsi.github.io/TheBookOfOhdsi/ — PhenotypeLibrary: https://ohdsi.github.io/PhenotypeLibrary/ — CIRCE: https://github.com/OHDSI/circe-be

[5] Ahmadi N, Peng Y, Nakhla M, et al. "A comparative patient-level prediction study in OMOP CDM: applicative potential and insights from synthetic data." *Scientific Reports*. 2024;14:2287. DOI: 10.1038/s41598-024-52723-y.

[6] OHDSI ETL-Synthea. https://ohdsi.github.io/ETL-Synthea/

[7] Yao S, Zhao J, Yu D, et al. "ReAct: Synergizing Reasoning and Acting in Language Models." ICLR 2023. arXiv:2210.03629.

[8] Li M, Song F, Yu B, et al. "API-Bank: A Comprehensive Benchmark for Tool-Augmented LLMs." EMNLP 2023, pp. 3102-3116. DOI: 10.18653/v1/2023.emnlp-main.187.

[9] Patil SG, Zhang T, Wang X, et al. "The Berkeley Function Calling Leaderboard." ICML 2025 (PMLR 267), pp. 48371-48392. https://proceedings.mlr.press/v267/patil25a.html

[10] Wang Q, et al. "Beyond Accuracy: A Cognitive Load Framework for Mapping the Capability Boundaries of Tool-use Agents." AAAI 2026. arXiv:2601.20412.

[11] Grace M, et al. "Demystifying evals for AI agents." Anthropic Engineering Blog. 2026. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

[12] Singh A, et al. "A Survey of the Model Context Protocol (MCP)." Preprints, 2025040245. DOI: 10.20944/preprints202504.0245.v1.

[13] Qin Y, Liang S, Ye Y, et al. "ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs." ICLR 2024 (Spotlight). arXiv:2307.16789.

[14] Databricks. "Beyond the Leaderboard: Unpacking Function Calling Eval." 2024. https://www.databricks.com/blog/unpacking-function-calling-eval

[15] Braylan A, Lease M. "Towards Reproducible LLM Evaluation: Quantifying Uncertainty in LLM Benchmark Scores." arXiv:2410.03492. 2024.

[16] Lee S, Yoo H, et al. "MI-CLEAR-LLM: Minimum Reporting Items for Clear Evaluation of Accuracy Reports of Large Language Models in Healthcare." *Korean J Radiology*. 2024;25(10):865-872. PubMed ID: 39344542. Updated 2025: https://kjronline.org/DOIx.php?id=10.3348/kjr.2025.1522

[17] Kim S, Lee S, et al. "Adherence to MI-CLEAR-LLM guidelines in published LLM studies." 2025. PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC11955383/

[18] Clinical task temperature evaluation. medRxiv 2024. https://www.medrxiv.org/content/10.1101/2024.07.22.24310824v1

[19] Emergency medicine temperature study. medRxiv 2025. https://www.medrxiv.org/content/10.1101/2025.06.04.25328288v2

[20] "Hot or Cold? Adaptive Temperature Sampling for Code Generation with Large Language Models." arXiv:2506.07295. 2025.

[21] Laban P, Bansal H, et al. "LLMs Get Lost In Multi-Turn Conversation." arXiv:2505.06120. 2025.

[22] Sharma M, et al. "ResearchRubrics: A Benchmark of Prompts and Rubrics For Evaluating Deep Research Agents." arXiv:2511.07685. 2025.

[23] Zhong H, et al. "ComplexFuncBench: Exploring Multi-Step and Constrained Function Calling under Long-Context Scenario." arXiv:2501.10132. 2025.

[24] Winston C, Just R. "A Taxonomy of Failures in Tool-Augmented LLMs." AST 2025. DOI: 10.1109/AST63371.2025.00019.

[25] Cemri M, et al. "Why Do Multi-Agent LLM Systems Fail?" arXiv:2503.13657. 2025.

[26] Hripcsak G, Rothschild AS. "Agreement, the F-Measure, and Reliability in Information Retrieval." *J Am Med Inform Assoc*. 2005;12(3):296-298. DOI: 10.1197/jamia.M1733.

[27] Hripcsak G, Albers DJ. "Next-generation phenotyping of electronic health records." *J Am Med Inform Assoc*. 2013;20(1):117-121. DOI: 10.1136/amiajnl-2012-001145.

[28] Bowyer S, Aitchison L, Ivanova DR. "Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints." ICML 2025, PMLR 267, pp. 81143-81184.

[29] Jiang D, et al. "MedAgentBench: A Virtual EHR Environment to Benchmark Medical LLM Agents." *NEJM AI*. 2025. arXiv:2501.14654.

[30] Shenzhang S, et al. "OMCP: Model Context Protocol Servers for the OMOP Common Data Model." OHDSI 2025 Global Symposium.

[31] Wang Z, et al. "MCP-Bench: Benchmarking Tool-Using LLM Agents with Complex Real-World Tasks via MCP Servers." arXiv:2508.20453. 2025.

[32] Livingston L, Featherstone-Uwague A, Barry A, et al. "Reproducible generative artificial intelligence evaluation for health care: a clinician-in-the-loop approach." *JAMIA Open*. 2025;8(3):ooaf054. DOI: 10.1093/jamiaopen/ooaf054.

[33] Cowie MR, Blomster JI, Curtis LH, et al. "Electronic health records to facilitate clinical research." *Clin Res Cardiol*. 2017;106(1):1-9. DOI: 10.1007/s00392-016-1025-6.

[34] Smith D. "OHDSI Agent Evaluation Database: Synthea 100K Synthetic OMOP CDM." Zenodo. 2026. DOI: 10.5281/zenodo.18726343. https://doi.org/10.5281/zenodo.18726343
