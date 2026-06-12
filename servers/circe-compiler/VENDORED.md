# circe-compiler — Emory clean-room reimplementation of OHDSI CIRCE

This directory vendors **circe-compiler**, Emory's deterministic OHDSI CIRCE
cohort-definition compiler (JSON → SQL via SQLGlot), exposed as an MCP server.
It is the cohort-construction + compilation server in the three-server
evaluated architecture.

- **Reimplements:** [`OHDSI/circe-be`](https://github.com/OHDSI/circe-be) (the
  Java CIRCE backend used by ATLAS and the `CirceR` HADES package), Apache-2.0.
- **Relationship:** a **clean-room reimplementation of CIRCE's compilation
  semantics in Python**, not a port of circe-be's code. The two share only the
  OHDSI cohort-definition JSON **interoperability standard** (the input format
  used by ATLAS and the Phenotype Library) and the same target logical
  structure (codeset table → primary events → inclusion rules → era-collapsed
  final cohort). They share **no code-generation mechanism**: circe-be
  interpolates FreeMarker string templates and adapts dialects with
  SqlRender/SqlTranslate; this implementation assembles SQL programmatically and
  optimizes/transpiles via the SQLGlot AST, with no JVM. The code here is
  independently authored.
- **License:** **Apache-2.0** (Emory's original expression); see the top-level
  `LICENSE`. Attribution to `OHDSI/circe-be` (also Apache-2.0) is offered as a
  **courtesy** acknowledgment of the algorithm and JSON standard this
  implementation follows.
- **Provisional note:** the clean-room determination was made without a
  line-level diff against the canonical `OHDSI/circe-be` source (it was not
  available at documentation time). It is well-supported by the difference in
  mechanism, language, and feature-gap profile, but should be confirmed by a
  circe-be diff before being treated as final. If that diff reveals copied
  FreeMarker templates or SQL, Apache-2.0's attribution/NOTICE terms attach to
  those portions.

Run it against the same DuckDB evaluation database as the other two servers.
