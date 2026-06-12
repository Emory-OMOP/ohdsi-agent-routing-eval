"""Core logic for OMOP concept search."""

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts, MAX_RESULTS


def search_concepts_core(
    keyword: str,
    domain: str | None = None,
    vocabulary_id: str | None = None,
    concept_class: str | None = None,
    standard_only: bool = True,
    valid_only: bool = True,
    limit: int = 25,
) -> list[dict]:
    """Search OMOP vocabulary concepts by keyword with optional filters.

    Returns list of dicts with keys: concept_id, concept_name, domain_id,
    vocabulary_id, concept_class_id, standard_concept, concept_code, invalid_reason.
    """
    limit = min(max(1, limit), MAX_RESULTS)

    conditions = ["c.concept_name ILIKE ?"]
    params: list = [f"%{keyword}%"]

    if domain:
        conditions.append("c.domain_id ILIKE ?")
        params.append(domain)

    if vocabulary_id:
        conditions.append("c.vocabulary_id ILIKE ?")
        params.append(vocabulary_id)

    if concept_class:
        conditions.append("c.concept_class_id ILIKE ?")
        params.append(concept_class)

    if standard_only:
        conditions.append("c.standard_concept = 'S'")

    if valid_only:
        conditions.append("c.invalid_reason IS NULL")

    where = " AND ".join(conditions)

    sql = f"""
        SELECT
            c.concept_id,
            c.concept_name,
            c.domain_id,
            c.vocabulary_id,
            c.concept_class_id,
            c.standard_concept,
            c.concept_code,
            c.invalid_reason
        FROM {qualified_vocab_table('concept')} c
        WHERE {where}
        ORDER BY
            CASE WHEN c.concept_name ILIKE ? THEN 0 ELSE 1 END,
            length(c.concept_name),
            c.concept_name
        LIMIT ?
    """
    all_params = params + [keyword, limit]

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "standard_concept", "concept_code", "invalid_reason",
    ]

    with get_connection() as conn:
        results = conn.execute(sql, all_params).fetchall()

    return rows_to_dicts(results, columns)
