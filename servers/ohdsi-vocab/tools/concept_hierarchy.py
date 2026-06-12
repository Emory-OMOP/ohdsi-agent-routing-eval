"""Hierarchy tools: get_concept_ancestors and get_concept_descendants."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.hierarchy import get_ancestors_core, get_descendants_core


def _format_hierarchy_table(rows: list[dict], header: str) -> str:
    """Format hierarchy results with separation columns."""
    lines = [header, ""]
    if not rows:
        lines.append("No results found.")
        return "\n".join(lines)

    lines.append(
        "| concept_id | concept_name | domain | vocab | class | "
        "min_sep | max_sep |"
    )
    lines.append(
        "|:-----------|:-------------|:-------|:------|:------|"
        ":--------|:--------|"
    )
    for r in rows:
        lines.append(
            f"| {r['concept_id']} | {r['concept_name'][:50]} | "
            f"{r['domain_id']} | {r['vocabulary_id']} | "
            f"{r['concept_class_id']} | {r['min_separation']} | "
            f"{r['max_separation']} |"
        )
    lines.append(f"\n*{len(rows)} result(s) found.*")
    return "\n".join(lines)


def register_hierarchy_tools(mcp: FastMCP):

    @mcp.tool()
    async def get_concept_ancestors(
        concept_id: int,
        max_separation: int | None = None,
        limit: int = 50,
    ) -> str:
        """Get all ancestor concepts of a given concept in the OMOP hierarchy.

        Walks UP the hierarchy from a specific concept to its parents,
        grandparents, etc. Uses the precomputed CONCEPT_ANCESTOR table for
        efficient traversal.

        Useful for understanding how specific a concept is, finding broader
        categories, and verifying a concept sits at the right level for
        a cohort definition.

        Args:
            concept_id: The OMOP concept_id to find ancestors for
            max_separation: Maximum levels of separation (None = all levels)
            limit: Maximum results (1-50). Default: 50
        """
        rows, source_name = get_ancestors_core(concept_id, max_separation, limit)
        header = f"## Ancestors of: {source_name} (ID: {concept_id})"
        return _format_hierarchy_table(rows, header)

    @mcp.tool()
    async def get_concept_descendants(
        concept_id: int,
        max_separation: int | None = None,
        limit: int = 50,
    ) -> str:
        """Get all descendant concepts of a given concept in the OMOP hierarchy.

        Walks DOWN the hierarchy from a specific concept to its children,
        grandchildren, etc. Uses the precomputed CONCEPT_ANCESTOR table for
        efficient traversal.

        Useful for finding more specific concepts, understanding the breadth
        of a concept set, and previewing what descendant inclusion will
        capture in a cohort definition.

        Args:
            concept_id: The OMOP concept_id to find descendants for
            max_separation: Maximum levels of separation (None = all levels)
            limit: Maximum results (1-50). Default: 50
        """
        rows, source_name = get_descendants_core(concept_id, max_separation, limit)
        header = f"## Descendants of: {source_name} (ID: {concept_id})"
        return _format_hierarchy_table(rows, header)
