# circe-compiler

**OHDSI CIRCE cohort definition compiler — JSON to optimized SQL, exposed as MCP tools.**

Replaces the Java/JVM CIRCE backend (`circe-be`) with a pure Python implementation using SQLGlot for AST-based SQL construction, optimization, and dialect transpilation. Designed to plug into the [FastOMOP/OMCP](https://github.com/fastomop/omcp) ecosystem as a complementary MCP server.

## Why This Exists

| | CIRCE (Java) | This compiler (Python) |
|---|---|---|
| **Architecture** | FreeMarker string templates | SQLGlot AST construction |
| **Optimization** | None | Built-in (predicate pushdown, constant folding) |
| **Dialect support** | OHDSI SQL → SqlRender/SqlTranslate | SQLGlot native (8+ dialects) |
| **SQL → JSON** | No | Planned (AST enables reverse direction) |
| **Observability** | None | Compilation trace, complexity scoring, segment tagging |
| **Validation** | Schema only | Semantic (invalid codeset refs, impossible windows, perf risks) |
| **Runtime** | JVM required | Pure Python, no JVM |
| **Agent-ready** | No | MCP server with 5 tools + schema resource |

## Quick Start

```bash
# Run the demo (no external deps needed)
python3 demo.py

# Install for production use
uv venv && uv pip install -e ".[dev]"

# Run tests
pytest tests/

# Run as MCP server
python -m circe_compiler
```

## MCP Tools

When running as an MCP server, these tools are exposed:

| Tool | Description |
|---|---|
| `compile_cohort_definition` | JSON → SQL (deterministic, auditable) |
| `validate_cohort_definition` | Semantic validation beyond schema checks |
| `analyze_cohort_complexity` | Static analysis + performance prediction |
| `transpile_sql_dialect` | SQL dialect conversion (replaces SqlRender) |
| `cohort_dry_run` | Preview without executing |

#### Resources

| URI | Description |
|---|---|
| `circe://schema/cohort-definition` | CIRCE JSON structure reference with examples |

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "circe_compiler": {
      "command": "python",
      "args": ["-m", "circe_compiler"]
    }
  }
}
```

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  ATLAS / Agent /  │     │  circe-compiler  │     │  OMOP Database   │
│  Human w/ JSON    │────>│  (MCP Server)    │────>│  (via OMCP)      │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                              │
                         ┌────┴────┐
                         v         v
                    Pydantic   SQLGlot
                    Models     AST/Optimizer
```

**Two paths to SQL in the FastOMOP ecosystem:**

1. **LLM-generated** (OMCP `Generate_SQL`): Natural language → SQL. Flexible, non-deterministic.
2. **Compiled** (this tool `compile_cohort_definition`): JSON → SQL. Deterministic, auditable, reproducible.

Clinical research needs both. Use OMCP for exploration, this compiler for validated study definitions.

## Compilation Output

Every compilation returns not just SQL but full diagnostics:

```python
from circe_compiler.mcp.server import compile_cohort

result = compile_cohort(
    cohort_json,
    dialect="postgres",
    cdm_schema="cdm",
    results_schema="results",
)

result["sql"]              # The executable SQL
result["segments"]         # Individual SQL statements
result["complexity"]       # Concept count, tables scanned, risk factors
result["template_trace"]   # Which domains activated and why
result["warnings"]         # Performance and correctness warnings
result["validation"]       # Semantic validation results
```

## Supported OMOP Domains

- ConditionOccurrence, DrugExposure, ProcedureOccurrence
- Measurement, Observation, VisitOccurrence, VisitDetail
- ConditionEra, DrugEra, DoseEra
- Death, DeviceExposure, Specimen
- ObservationPeriod, PayerPlanPeriod
- Demographics (Age, Gender, Race, Ethnicity)

## Supported SQL Dialects

PostgreSQL, DuckDB, SQL Server (TSQL), Redshift, Snowflake, BigQuery, Spark, Trino

## Project Structure

```
circe_compiler/
├── demo.py                          # Self-contained demo (no deps)
├── pyproject.toml                   # Project config
├── src/circe_compiler/
│   ├── __init__.py
│   ├── __main__.py                  # MCP server entry point
│   ├── models/
│   │   └── cohort_expression.py     # Full Pydantic models for CIRCE JSON
│   ├── compiler/
│   │   └── sql_builder.py           # SQLGlot-based SQL generation
│   ├── validation/
│   │   └── validator.py             # Semantic validation service
│   └── mcp/
│       └── server.py                # MCP tool definitions
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   └── t2dm_metformin_no_hf.json  # Example cohort definition
    └── test_compiler.py
```

## Contributing to FastOMOP

This project is designed to be contributed to the [FastOMOP](https://github.com/fastomop) organization as an additional MCP server alongside OMCP. The compilation tools complement OMCP's `Generate_SQL` with deterministic compilation from structured definitions.

## License

Apache-2.0 (see the top-level `LICENSE`).
