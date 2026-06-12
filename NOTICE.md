# Third-Party Components and Attribution

This repository builds on the following open-source projects and standards. Each is the property of its respective authors and is governed by its own license. This NOTICE is informational; see each project for its license terms.

## Standards and data models

- **OMOP Common Data Model** (v5.4) and the **OHDSI** open-source ecosystem (Observational Health Data Sciences and Informatics). https://www.ohdsi.org/ — *The Book of OHDSI*, https://ohdsi.github.io/TheBookOfOhdsi/
- **CIRCE** — cohort-definition compilation. The `servers/circe-compiler/` MCP server is Emory's **clean-room Python/SQLGlot reimplementation** of the OHDSI Java CIRCE backend ([`OHDSI/circe-be`](https://github.com/OHDSI/circe-be), Apache-2.0), following the OHDSI cohort-definition JSON standard. Licensed Apache-2.0; courtesy attribution to OHDSI/circe-be. See `servers/circe-compiler/VENDORED.md`.
- **OHDSI PhenotypeLibrary** ([`OHDSI/PhenotypeLibrary`](https://github.com/OHDSI/PhenotypeLibrary), Apache-2.0) and **OHDSI QueryLibrary** ([`OHDSI/QueryLibrary`](https://github.com/OHDSI/QueryLibrary), Apache-2.0) — peer-reviewed cohort definitions and community SQL templates surfaced by the `ohdsi-vocab` tools. Content was pulled from upstream HEAD (~2026-02-17, exact commit unrecorded); see the reproducibility caveat in `docs/PROVENANCE.md`.
- **OMOP Standardized Vocabularies** — distributed via OHDSI Athena (release v5.0, 27-Feb-2025); per-source vocabulary licenses apply and the vocabulary files are not redistributed here.
- **Model Context Protocol (MCP)** — the open client/server tool-calling standard. https://modelcontextprotocol.io/

## Synthetic data

- **Synthea™** (v3.0.0, Apache-2.0) — synthetic patient generator (The MITRE Corporation), used to generate the 100,000-patient OMOP CDM evaluation database. https://github.com/synthetichealth/synthea — Walonoski J, et al. *J Am Med Inform Assoc.* 2018;25(3):230–238.
- **OHDSI ETL-Synthea** — Synthea-to-OMOP load pipeline. https://github.com/OHDSI/ETL-Synthea

## Software

- **DuckDB** — embedded analytical database engine used for the evaluation CDM. https://duckdb.org/
- **FastMCP** — Python framework used to build the `ohdsi-vocab` and `circe-compiler` MCP servers. https://github.com/jlowin/fastmcp
- **omcp** — third-party OMOP MCP server providing read-only SQL execution (the `omcp` server in the three-server architecture), by **fastomop** (https://github.com/fastomop/omcp, docs at https://fastomop.github.io/omcp/), MIT-licensed (Copyright © 2025 fastomop). The code in `servers/omcp/` is derived from `fastomop/omcp@4922d41` with the modifications documented in `docs/PROVENANCE.md`; the original MIT license is preserved verbatim in `servers/omcp/LICENSE`. See `servers/omcp/VENDORED.md`.
- **FastAPI** and **Uvicorn** — the webapp / LLM-client framework. https://fastapi.tiangolo.com/
- **Caddy** — reverse proxy used by the webapp deployment. https://caddyserver.com/
- **Ollama** — local model serving for the open-weight (Qwen3) models. https://ollama.com/

## Evaluated models

The models evaluated in this study are the property of their respective providers: **Claude** (Anthropic), **Qwen3** (Alibaba, open-weight, run locally via Ollama), and **DeepSeek** (DeepSeek). They were accessed for evaluation only and are not redistributed here.
