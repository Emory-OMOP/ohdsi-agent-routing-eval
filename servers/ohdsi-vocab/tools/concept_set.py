"""preview_concept_set tool: Resolve concept sets with optional descendant inclusion."""

from mcp.server.fastmcp import FastMCP

from omop_vocab_core.concept_set import preview_concept_set_core


def register_concept_set_tools(mcp: FastMCP):

    @mcp.tool()
    async def preview_concept_set(
        concept_ids: list[int],
        include_descendants: bool = True,
        limit: int = 50,
    ) -> str:
        """Preview/resolve a concept set by expanding concept_ids with their descendants.

        Given a list of concept_ids, resolves the full concept set by optionally
        including all descendant concepts from the CONCEPT_ANCESTOR table.
        This is the core operation behind OHDSI cohort definitions — use it to
        verify which concepts will be included before building a cohort.

        After previewing a concept set here, the concept_ids can be used in
        a CIRCE cohort definition JSON and compiled to executable SQL with
        cohort compiler tools.

        Args:
            concept_ids: List of OMOP concept_ids to include in the set
            include_descendants: If True, include all descendants of each concept. Default: True
            limit: Maximum total concepts to return (1-50). Default: 50
        """
        if not concept_ids:
            return "Error: concept_ids list cannot be empty."

        rows, total_count = preview_concept_set_core(
            concept_ids, include_descendants, limit,
        )

        input_ids_str = ", ".join(str(cid) for cid in concept_ids)
        desc_str = " (with descendants)" if include_descendants else " (exact IDs only)"

        lines = [
            f"## Concept Set Preview{desc_str}",
            f"Input concept_ids: [{input_ids_str}]",
            f"Total resolved concepts: {total_count}",
            "",
        ]

        if not rows:
            lines.append("No valid concepts found for the given IDs.")
            return "\n".join(lines)

        lines.append(
            "| concept_id | concept_name | domain | vocab | class | "
            "std | source |"
        )
        lines.append(
            "|:-----------|:-------------|:-------|:------|:------|"
            ":----|:-------|"
        )
        for r in rows:
            source = "input" if r["is_descendant"] == 0 else "descendant"
            std = r.get("standard_concept") or ""
            lines.append(
                f"| {r['concept_id']} | {r['concept_name'][:50]} | "
                f"{r['domain_id']} | {r['vocabulary_id']} | "
                f"{r['concept_class_id']} | {std} | {source} |"
            )

        if total_count > limit:
            lines.append(
                f"\n*Showing {len(rows)} of {total_count} total concepts. "
                f"Increase limit to see more.*"
            )
        else:
            lines.append(f"\n*{len(rows)} concept(s) in resolved set.*")

        return "\n".join(lines)
