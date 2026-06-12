#!/usr/bin/env python3
"""OHDSI OMOP Vocabulary MCP Server.

Provides vocabulary lookup tools for an AI agent working with OMOP CDM data.
Queries a local DuckDB instance containing the full Athena vocabulary (7.4M concepts).
"""

import os
import sys
from pathlib import Path

# Add mcp_server/ to sys.path so submodule imports work when run directly
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

from tools.search_concepts import register_search_concepts
from tools.concept_lookup import register_concept_lookup
from tools.concept_hierarchy import register_hierarchy_tools
from tools.concept_relationships import register_relationship_tools
from tools.concept_set import register_concept_set_tools
from tools.table_schema import register_table_schema_tools
from tools.phenotype_library import register_phenotype_library_tools
from tools.query_library import register_query_library_tools
from resources.omop_docs import register_resources
from prompts.concept_search import register_prompts

mcp = FastMCP(
    "ohdsi-vocab",
    instructions=(
        "OHDSI OMOP Vocabulary search and navigation tools. "
        "Provides deep access to 7.4M+ standardized clinical concepts "
        "from SNOMED, RxNorm, LOINC, ICD10CM, and 60+ other vocabularies "
        "via a local DuckDB instance.\n\n"
        "This server handles vocabulary lookups: finding concepts by name, "
        "navigating hierarchies, exploring relationships, and resolving "
        "concept sets for cohort definitions.\n\n"
        "For ad-hoc SQL queries against clinical data tables (person, "
        "condition_occurrence, drug_exposure, etc.), use a SQL execution "
        "tool if one is connected. For compiling OHDSI cohort definitions "
        "to SQL, use cohort compiler tools if available."
    ),
)

register_search_concepts(mcp)
register_concept_lookup(mcp)
register_hierarchy_tools(mcp)
register_relationship_tools(mcp)
register_concept_set_tools(mcp)
register_table_schema_tools(mcp)
register_phenotype_library_tools(mcp)
register_query_library_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8001"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
