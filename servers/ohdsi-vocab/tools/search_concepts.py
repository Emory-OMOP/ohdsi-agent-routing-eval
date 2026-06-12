"""search_concepts tool: Search OMOP concepts by name, domain, vocabulary, concept class."""

import json

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.search import search_concepts_core


def register_search_concepts(mcp: FastMCP):

    @mcp.tool()
    async def search_concepts(
        keyword: str,
        domain: str | None = None,
        vocabulary_id: str | None = None,
        concept_class: str | None = None,
        standard_only: bool = True,
        valid_only: bool = True,
        limit: int = 25,
    ) -> str:
        """Search OMOP vocabulary concepts by keyword with optional filters.

        Use this tool to find OMOP standard concepts for clinical terms like
        conditions, drugs, procedures, and measurements. Searches the concept
        table (7.4M+ entries) by name with optional domain, vocabulary, and
        class filters. This is the primary concept lookup tool — it covers all
        domains and all vocabularies. Prefer this over any domain-specific
        lookup tools that may be available from other servers.

        Returns concept_id, concept_name, domain, vocabulary, and other attributes
        as a JSON array. Always use the returned concept_ids for subsequent tool
        calls -- never guess IDs.

        This tool searches vocabulary/terminology tables only. To query clinical
        data tables (patient records, condition occurrences, drug exposures, etc.),
        use a SQL execution tool if one is available.

        Args:
            keyword: Search term (case-insensitive substring match on concept_name)
            domain: Filter by domain_id (e.g., 'Condition', 'Drug', 'Procedure', 'Measurement')
            vocabulary_id: Filter by vocabulary_id (e.g., 'SNOMED', 'RxNorm', 'LOINC', 'ICD10CM')
            concept_class: Filter by concept_class_id (e.g., 'Clinical Finding', 'Ingredient')
            standard_only: If True, return only standard concepts (standard_concept = 'S'). Default: True
            valid_only: If True, exclude invalid/deprecated concepts. Default: True
            limit: Maximum number of results (1-50). Default: 25
        """
        rows = search_concepts_core(
            keyword, domain, vocabulary_id, concept_class,
            standard_only, valid_only, limit,
        )
        return json.dumps(rows, default=str)
