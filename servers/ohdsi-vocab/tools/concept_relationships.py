"""get_concept_relationships tool: Find relationships for a concept."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.relationships import get_relationships_core


def register_relationship_tools(mcp: FastMCP):

    @mcp.tool()
    async def get_concept_relationships(
        concept_id: int,
        relationship_id: str | None = None,
        valid_only: bool = True,
        limit: int = 50,
    ) -> str:
        """Get relationships for a concept (Maps to, Has ingredient, Is a, etc.).

        Returns all related concepts connected to the given concept_id via
        CONCEPT_RELATIONSHIP. Common relationship types:
        - 'Maps to': Non-standard to standard concept mapping
        - 'Is a': Hierarchical parent relationship
        - 'Has ingredient': Drug to ingredient
        - 'Has finding site': Condition to body site

        Args:
            concept_id: The OMOP concept_id to find relationships for
            relationship_id: Filter by relationship type (e.g., 'Maps to', 'Is a')
            valid_only: Exclude invalid relationships. Default: True
            limit: Maximum results (1-50). Default: 50
        """
        rows, source_name, source_vocab = get_relationships_core(
            concept_id, relationship_id, valid_only, limit,
        )

        filter_str = f" (filtered: {relationship_id})" if relationship_id else ""
        lines = [
            f"## Relationships for: {source_name} (ID: {concept_id}, Vocab: {source_vocab}){filter_str}",
            "",
        ]

        if not rows:
            lines.append("No relationships found.")
            return "\n".join(lines)

        lines.append(
            "| relationship | related_id | related_name | domain | vocab | "
            "class | std | code |"
        )
        lines.append(
            "|:-------------|:-----------|:-------------|:-------|:------|"
            ":------|:----|:-----|"
        )
        for r in rows:
            std = r.get("standard_concept") or ""
            lines.append(
                f"| {r['relationship_id']} | {r['related_concept_id']} | "
                f"{r['related_concept_name'][:40]} | {r['domain_id']} | "
                f"{r['vocabulary_id']} | {r['concept_class_id']} | "
                f"{std} | {r['concept_code']} |"
            )

        lines.append(f"\n*{len(rows)} relationship(s) found.*")
        return "\n".join(lines)
