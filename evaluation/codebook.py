"""Scoring codebook: 33 PromptRule implementations (P01-P33) for the OHDSI Agent evaluation.

Categories C1-C8. P19 and P21 accept both Select_Query and build_cohort_definition
paths to support the two-condition evaluation design (open vs guided).

Each rule's evaluate() method returns a score dict with:
    result: PASS | PARTIAL | FAIL
    parameters_correct: CORRECT | PARTIAL | INCORRECT | N/A
    needs_review: bool
    auto_notes: str
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scorers import (
    check_concept_id_in_args,
    check_keyword_relevance,
    check_param,
    check_sql_contains,
    count_tool,
    get_args_for_tool,
    has_all_tools,
    has_any_tool,
    has_tool,
    make_score,
    only_tool_before,
    tools_in_order,
)


class PromptRule(Protocol):
    """Protocol for a prompt scoring rule."""

    prompt_id: int
    category_code: str

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict: ...


# ── C1: Single Tool Selection ────────────────────────────────────────────


@dataclass
class P01:
    prompt_id: int = 1
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "search_phenotypes"):
            return make_score("FAIL", "N/A", notes="search_phenotypes never called")

        args = get_args_for_tool(tools, arguments, "search_phenotypes")
        kw_ok = check_keyword_relevance(args, ["atrial", "fibrillation", "afib", "af"])

        if has_tool(tools, "search_concepts") and tools.index("search_concepts") < tools.index("search_phenotypes"):
            return make_score("PARTIAL", "CORRECT" if kw_ok else "INCORRECT",
                              notes="search_phenotypes preceded by unnecessary search_concepts")

        return make_score("PASS", "CORRECT" if kw_ok else "INCORRECT")


@dataclass
class P02:
    prompt_id: int = 2
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "search_query_patterns"):
            return make_score("FAIL", "N/A", notes="search_query_patterns never called")

        args = get_args_for_tool(tools, arguments, "search_query_patterns")
        kw_ok = check_keyword_relevance(args, ["drug", "exposure", "drug_exposure"])

        if has_tool(tools, "Select_Query"):
            return make_score("PARTIAL", "CORRECT" if kw_ok else "INCORRECT",
                              notes="also called Select_Query unnecessarily")

        return make_score("PASS", "CORRECT" if kw_ok else "INCORRECT")


@dataclass
class P03:
    prompt_id: int = 3
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "get_phenotype"):
            return make_score("FAIL", "N/A", notes="get_phenotype never called")

        args = get_args_for_tool(tools, arguments, "get_phenotype")
        id_ok = (check_param(args, "id", 77, "equals")
                 or check_param(args, "phenotype_id", 77, "equals")
                 or check_param(args, "cohort_id", 77, "equals"))

        if has_tool(tools, "search_phenotypes") and tools.index("search_phenotypes") < tools.index("get_phenotype"):
            return make_score("PARTIAL", "CORRECT" if id_ok else "INCORRECT",
                              notes="preceded by search_phenotypes")

        if not id_ok:
            return make_score("FAIL", "INCORRECT", notes="wrong phenotype ID")

        return make_score("PASS", "CORRECT")


@dataclass
class P04:
    prompt_id: int = 4
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "get_concept"):
            args = get_args_for_tool(tools, arguments, "get_concept")
            id_ok = check_concept_id_in_args(args, 201826)
            return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

        if has_tool(tools, "search_concepts"):
            return make_score("PARTIAL", "PARTIAL",
                              notes="search_concepts used instead of get_concept (indirect)")

        return make_score("FAIL", "N/A", notes="no concept tool called")


@dataclass
class P05:
    prompt_id: int = 5
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "get_concept_relationships"):
            args = get_args_for_tool(tools, arguments, "get_concept_relationships")
            id_ok = check_concept_id_in_args(args, 201826)
            return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

        if has_any_tool(tools, ["get_concept_ancestors", "get_concept_descendants"]):
            return make_score("PARTIAL", "PARTIAL",
                              notes="ancestors/descendants called instead of relationships")

        return make_score("FAIL", "N/A", notes="no relationship tool called")


@dataclass
class P06:
    prompt_id: int = 6
    category_code: str = "C1"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "preview_concept_set"):
            return make_score("FAIL", "N/A", notes="preview_concept_set not called")

        args = get_args_for_tool(tools, arguments, "preview_concept_set")
        has_201826 = check_concept_id_in_args(args, 201826)
        has_4193704 = check_concept_id_in_args(args, 4193704)
        both_ids = has_201826 and has_4193704

        # Check include_descendants
        desc_ok = (
            check_param(args, "include_descendants", True, "equals")
            or check_param(args, "includeDescendants", True, "equals")
            or check_param(args, "include_descendants", "true", "equals")
            or check_param(args, "include_descendants", "True", "equals")
        )

        if both_ids and desc_ok:
            return make_score("PASS", "CORRECT")

        if not both_ids and not desc_ok:
            return make_score("PARTIAL", "INCORRECT",
                              notes="missing concept_ids and descendants flag")
        return make_score("PARTIAL", "PARTIAL",
                          notes=f"ids={'both' if both_ids else 'missing'}, descendants={'ok' if desc_ok else 'missing'}")


# ── C2: Tool Disambiguation ─────────────────────────────────────────────


@dataclass
class P07:
    prompt_id: int = 7
    category_code: str = "C2"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "search_phenotypes") and not has_tool(tools, "search_concepts"):
            return make_score("FAIL", "N/A",
                              notes="search_phenotypes called instead of search_concepts")

        if not has_tool(tools, "search_concepts"):
            return make_score("FAIL", "N/A", notes="search_concepts not called")

        args = get_args_for_tool(tools, arguments, "search_concepts")
        kw_ok = check_keyword_relevance(args, ["diabetes", "type 2", "t2dm", "type2"])

        # Check for standard/SNOMED filter.
        # standard_only defaults to True in the API, so absent = True (correct).
        has_filter = (
            not check_param(args, "standard_only", False, "equals")  # absent or True → ok
            or check_param(args, "vocabulary_id", "SNOMED", "contains")
            or check_param(args, "standard_concept", check_type="truthy")
        )

        if kw_ok and has_filter:
            return make_score("PASS", "CORRECT")

        if kw_ok:
            return make_score("PARTIAL", "PARTIAL",
                              notes="search_concepts called with standard_only=False")

        return make_score("PARTIAL", "INCORRECT", notes="search_concepts called, weak keywords")


@dataclass
class P08:
    prompt_id: int = 8
    category_code: str = "C2"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "get_concept_descendants"):
            args = get_args_for_tool(tools, arguments, "get_concept_descendants")
            id_ok = check_concept_id_in_args(args, 201826)
            return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

        if has_tool(tools, "get_concept_relationships"):
            args = get_args_for_tool(tools, arguments, "get_concept_relationships")
            id_ok = check_concept_id_in_args(args, 201826)
            return make_score("PARTIAL", "CORRECT" if id_ok else "INCORRECT",
                              notes="get_concept_relationships called instead of get_concept_descendants")

        return make_score("FAIL", "N/A", notes="no hierarchy tool called")


@dataclass
class P09:
    prompt_id: int = 9
    category_code: str = "C2"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "get_concept_ancestors"):
            args = get_args_for_tool(tools, arguments, "get_concept_ancestors")
            id_ok = check_concept_id_in_args(args, 4193704)
            return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

        if has_tool(tools, "get_concept_descendants"):
            args = get_args_for_tool(tools, arguments, "get_concept_descendants")
            id_ok = check_concept_id_in_args(args, 4193704)
            return make_score("PARTIAL", "PARTIAL" if id_ok else "INCORRECT",
                              notes="get_concept_descendants called (wrong direction)")

        return make_score("FAIL", "N/A", notes="no hierarchy tool called")


@dataclass
class P10:
    prompt_id: int = 10
    category_code: str = "C2"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if has_tool(tools, "get_table_schema"):
            args = get_args_for_tool(tools, arguments, "get_table_schema")
            table_ok = check_param(args, "table_name", "measurement", "contains") or \
                       check_param(args, "table", "measurement", "contains")
            return make_score("PASS", "CORRECT" if table_ok else "INCORRECT")

        if has_tool(tools, "list_cdm_tables"):
            return make_score("PARTIAL", "PARTIAL", notes="list_cdm_tables called (too broad)")

        return make_score("FAIL", "N/A", notes="no schema tool called")


# ── C3: Intra-Server Chaining ───────────────────────────────────────────


@dataclass
class P11:
    prompt_id: int = 11
    category_code: str = "C3"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_phenotypes")
        has_get = has_tool(tools, "get_phenotype")

        if has_search and has_get and tools_in_order(tools, ["search_phenotypes", "get_phenotype"]):
            search_args = get_args_for_tool(tools, arguments, "search_phenotypes")
            kw_ok = check_keyword_relevance(search_args, ["diabetes", "type 2", "t2dm"])
            # Can't deterministically verify ID flows from search without tool_result data,
            # but we can check the get_phenotype args exist
            get_args = get_args_for_tool(tools, arguments, "get_phenotype")
            has_id = get_args is not None and (
                check_param(get_args, "id", check_type="exists")
                or check_param(get_args, "phenotype_id", check_type="exists")
                or check_param(get_args, "cohort_id", check_type="exists")
            )
            if kw_ok and has_id:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL" if has_id else "INCORRECT",
                              notes="chain correct but keyword/ID issues")

        if has_search and has_get:
            return make_score("PARTIAL", "PARTIAL", notes="both called but not in expected order")

        if has_search or has_get:
            which = "search_phenotypes" if has_search else "get_phenotype"
            return make_score("FAIL", "N/A", notes=f"only {which} called")

        return make_score("FAIL", "N/A", notes="neither tool called")


@dataclass
class P12:
    prompt_id: int = 12
    category_code: str = "C3"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_query_patterns")
        has_get = has_tool(tools, "get_query")

        if has_search and has_get and tools_in_order(tools, ["search_query_patterns", "get_query"]):
            search_args = get_args_for_tool(tools, arguments, "search_query_patterns")
            kw_ok = check_keyword_relevance(search_args, ["drug", "exposure"])
            return make_score("PASS", "CORRECT" if kw_ok else "PARTIAL")

        if has_search and not has_get:
            return make_score("PARTIAL", "PARTIAL", notes="only search_query_patterns called")

        if not has_search and not has_get:
            return make_score("FAIL", "N/A", notes="neither tool called")

        return make_score("PARTIAL", "PARTIAL", notes="tools called but not in expected order")


@dataclass
class P13:
    prompt_id: int = 13
    category_code: str = "C3"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_get = has_tool(tools, "get_concept")
        has_desc = has_tool(tools, "get_concept_descendants")

        if has_get and has_desc and tools_in_order(tools, ["get_concept", "get_concept_descendants"]):
            get_args = get_args_for_tool(tools, arguments, "get_concept")
            desc_args = get_args_for_tool(tools, arguments, "get_concept_descendants")
            id_in_get = check_concept_id_in_args(get_args, 313217)
            id_in_desc = check_concept_id_in_args(desc_args, 313217)
            if id_in_get and id_in_desc:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL", notes="chain correct but concept_id issues")

        if has_desc and not has_get:
            desc_args = get_args_for_tool(tools, arguments, "get_concept_descendants")
            id_ok = check_concept_id_in_args(desc_args, 313217)
            return make_score("PARTIAL", "CORRECT" if id_ok else "INCORRECT",
                              notes="skipped get_concept lookup")

        if not has_get and not has_desc:
            return make_score("FAIL", "N/A", notes="neither tool called")

        return make_score("PARTIAL", "PARTIAL", notes="incomplete chain")


@dataclass
class P14:
    prompt_id: int = 14
    category_code: str = "C3"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_rel = has_tool(tools, "get_concept_relationships")

        if has_search and has_rel and tools_in_order(tools, ["search_concepts", "get_concept_relationships"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["aspirin"])
            return make_score("PASS", "CORRECT" if kw_ok else "PARTIAL")

        if has_search and has_rel:
            return make_score("PARTIAL", "PARTIAL", notes="both called but wrong order")

        if not has_search and not has_rel:
            return make_score("FAIL", "N/A", notes="chain not attempted")

        return make_score("PARTIAL", "PARTIAL", notes="incomplete chain")


# ── C4: Cross-Server Chaining ───────────────────────────────────────────


@dataclass
class P15:
    prompt_id: int = 15
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        chain = ["search_phenotypes", "get_phenotype", "compile_cohort_definition"]
        present = sum(1 for t in chain if has_tool(tools, t))

        if present == 3 and tools_in_order(tools, chain):
            search_args = get_args_for_tool(tools, arguments, "search_phenotypes")
            kw_ok = check_keyword_relevance(search_args, ["heart", "failure", "hf"])
            return make_score("PASS", "CORRECT" if kw_ok else "PARTIAL")

        if present >= 2:
            return make_score("PARTIAL", "PARTIAL", notes=f"{present}/3 chain tools called")

        return make_score("FAIL", "N/A", notes=f"only {present}/3 chain tools called")


@dataclass
class P16:
    prompt_id: int = 16
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_get = has_tool(tools, "get_phenotype")
        has_validate = has_tool(tools, "validate_cohort_definition")

        if has_validate:
            # Direct phenotype_id path (no get_phenotype needed)
            val_args = get_args_for_tool(tools, arguments, "validate_cohort_definition")
            if check_param(val_args, "phenotype_id", 10, "equals"):
                return make_score("PASS", "CORRECT")

            # Legacy chain path: get_phenotype → validate with JSON relay
            if has_get and tools_in_order(tools, ["get_phenotype", "validate_cohort_definition"]):
                get_args = get_args_for_tool(tools, arguments, "get_phenotype")
                id_ok = (check_param(get_args, "id", 10, "equals")
                         or check_param(get_args, "phenotype_id", 10, "equals")
                         or check_param(get_args, "cohort_id", 10, "equals"))
                return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

            return make_score("PASS", "INCORRECT", notes="validate called but wrong phenotype")

        if has_get and not has_validate:
            return make_score("PARTIAL", "PARTIAL", notes="only get_phenotype called")

        return make_score("FAIL", "N/A", notes="vocab→circe chain not attempted")


@dataclass
class P17:
    prompt_id: int = 17
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_get = has_tool(tools, "get_phenotype")
        has_analyze = has_tool(tools, "analyze_cohort_complexity")

        if has_analyze:
            # Direct phenotype_id path (no get_phenotype needed)
            analyze_args = get_args_for_tool(tools, arguments, "analyze_cohort_complexity")
            if check_param(analyze_args, "phenotype_id", 288, "equals"):
                return make_score("PASS", "CORRECT")

            # Legacy chain path: get_phenotype → analyze with JSON relay
            if has_get and tools_in_order(tools, ["get_phenotype", "analyze_cohort_complexity"]):
                get_args = get_args_for_tool(tools, arguments, "get_phenotype")
                id_ok = (check_param(get_args, "id", 288, "equals")
                         or check_param(get_args, "phenotype_id", 288, "equals")
                         or check_param(get_args, "cohort_id", 288, "equals"))
                return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

            return make_score("PASS", "INCORRECT", notes="analyze called but wrong phenotype")

        if has_get and not has_analyze:
            return make_score("PARTIAL", "PARTIAL", notes="only get_phenotype called")

        return make_score("FAIL", "N/A", notes="no circe tool called")


@dataclass
class P18:
    prompt_id: int = 18
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_get = has_tool(tools, "get_phenotype")
        has_dry_run = has_tool(tools, "cohort_dry_run")
        has_compile = has_tool(tools, "compile_cohort_definition")

        if has_dry_run:
            # Direct phenotype_id path (no get_phenotype needed, any order)
            dr_args = get_args_for_tool(tools, arguments, "cohort_dry_run")
            if check_param(dr_args, "phenotype_id", 519, "equals"):
                return make_score("PASS", "CORRECT")

            # Legacy chain path: get_phenotype → dry_run with JSON relay
            if has_get and tools_in_order(tools, ["get_phenotype", "cohort_dry_run"]):
                get_args = get_args_for_tool(tools, arguments, "get_phenotype")
                id_ok = (check_param(get_args, "id", 519, "equals")
                         or check_param(get_args, "phenotype_id", 519, "equals")
                         or check_param(get_args, "cohort_id", 519, "equals"))
                return make_score("PASS", "CORRECT" if id_ok else "INCORRECT")

            return make_score("PASS", "INCORRECT", notes="dry_run called but wrong phenotype")

        if has_get and has_compile and not has_dry_run:
            return make_score("PARTIAL", "PARTIAL",
                              notes="compile_cohort_definition called instead of cohort_dry_run (overshot)")

        if has_get and not has_dry_run:
            return make_score("PARTIAL", "PARTIAL", notes="only get_phenotype called")

        return make_score("FAIL", "N/A", notes="no circe tool called")


@dataclass
class P19:
    prompt_id: int = 19
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_query = has_tool(tools, "Select_Query")
        has_build = has_tool(tools, "build_cohort_definition")

        # Path A: search_concepts → Select_Query (open condition natural path)
        if has_search and has_query and tools_in_order(tools, ["search_concepts", "Select_Query"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["diabetes", "type 2", "t2dm"])
            query_args = get_args_for_tool(tools, arguments, "Select_Query")
            sql_has_count = check_sql_contains(query_args, ["count", "condition"])
            if kw_ok and sql_has_count:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL", notes="chain correct, param issues")

        # Path B: search_concepts → build_cohort_definition (guided or builder-preferred)
        if has_search and has_build and tools_in_order(tools, ["search_concepts", "build_cohort_definition"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["diabetes", "type 2", "t2dm"])
            build_args = get_args_for_tool(tools, arguments, "build_cohort_definition")
            has_spec = check_param(build_args, "spec_json", check_type="exists")
            if kw_ok and has_spec:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL", notes="builder chain correct, param issues")

        # Ungrounded paths (no concept lookup first)
        if has_query and not has_search:
            return make_score("PARTIAL", "PARTIAL",
                              notes="Select_Query called without concept lookup (ungrounded)")
        if has_build and not has_search:
            return make_score("PARTIAL", "PARTIAL",
                              notes="build_cohort_definition called without concept lookup (ungrounded)")

        if not has_query and not has_build:
            return make_score("FAIL", "N/A", notes="no query or builder tool called")

        return make_score("PARTIAL", "PARTIAL", notes="partial chain")


@dataclass
class P20:
    prompt_id: int = 20
    category_code: str = "C4"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_schema = has_tool(tools, "get_table_schema")
        has_query = has_tool(tools, "Select_Query")

        if has_schema and has_query and tools_in_order(tools, ["get_table_schema", "Select_Query"]):
            schema_args = get_args_for_tool(tools, arguments, "get_table_schema")
            table_ok = check_param(schema_args, "table_name", "drug_exposure", "contains") or \
                       check_param(schema_args, "table", "drug_exposure", "contains")
            query_args = get_args_for_tool(tools, arguments, "Select_Query")
            sql_ok = check_sql_contains(query_args, ["count"])
            if table_ok and sql_ok:
                return make_score("PASS", "CORRECT")
            return make_score("PARTIAL", "PARTIAL", notes="chain correct but param issues")

        if (has_schema or has_query) and not (has_schema and has_query):
            return make_score("FAIL", "N/A", notes="only one tool called")

        return make_score("FAIL", "N/A", notes="neither tool called")


# ── C5: Parameter Construction ───────────────────────────────────────────


@dataclass
class P21:
    prompt_id: int = 21
    category_code: str = "C5"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_query = has_tool(tools, "Select_Query")
        has_build = has_tool(tools, "build_cohort_definition")

        if not has_search:
            return make_score("FAIL", "N/A", notes="missing concept lookup")

        search_args = get_args_for_tool(tools, arguments, "search_concepts")
        # standard_only defaults to True in the API, so absent = True (correct).
        standard_filter = (
            not check_param(search_args, "standard_only", False, "equals")  # absent or True → ok
            or check_param(search_args, "standard_concept", check_type="truthy")
        )

        # Path A: search_concepts → Select_Query (open condition natural path)
        if has_query and tools_in_order(tools, ["search_concepts", "Select_Query"]):
            query_args = get_args_for_tool(tools, arguments, "Select_Query")
            sql_has_concept = check_sql_contains(query_args, ["concept_id"])

            if standard_filter and sql_has_concept:
                return make_score("PASS", "CORRECT")

            notes_parts = []
            if not standard_filter:
                notes_parts.append("no standard_only filter")
            if not sql_has_concept:
                notes_parts.append("SQL missing concept_id")
            return make_score("PARTIAL", "PARTIAL", notes="; ".join(notes_parts))

        # Path B: search_concepts → build_cohort_definition (guided or builder-preferred)
        if has_build and tools_in_order(tools, ["search_concepts", "build_cohort_definition"]):
            build_args = get_args_for_tool(tools, arguments, "build_cohort_definition")
            has_spec = check_param(build_args, "spec_json", check_type="exists")

            if standard_filter and has_spec:
                return make_score("PASS", "CORRECT")

            notes_parts = []
            if not standard_filter:
                notes_parts.append("no standard_only filter")
            if not has_spec:
                notes_parts.append("build spec missing")
            return make_score("PARTIAL", "PARTIAL", notes="; ".join(notes_parts))

        if not has_query and not has_build:
            return make_score("FAIL", "N/A", notes="concept lookup done but no execution tool called")

        return make_score("PARTIAL", "PARTIAL", notes="tools called but not in expected order")


@dataclass
class P22:
    prompt_id: int = 22
    category_code: str = "C5"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_get = has_tool(tools, "get_phenotype")
        has_compile = has_tool(tools, "compile_cohort_definition")
        has_transpile = has_tool(tools, "transpile_sql_dialect")

        chain_count = sum([has_get, has_compile, has_transpile])

        if chain_count == 3 and tools_in_order(tools, ["get_phenotype", "compile_cohort_definition", "transpile_sql_dialect"]):
            get_args = get_args_for_tool(tools, arguments, "get_phenotype")
            id_ok = (check_param(get_args, "id", 519, "equals")
                     or check_param(get_args, "phenotype_id", 519, "equals")
                     or check_param(get_args, "cohort_id", 519, "equals"))

            compile_args = get_args_for_tool(tools, arguments, "compile_cohort_definition")
            dialect_ok = check_param(compile_args, "dialect", "postgresql", "contains") or \
                         check_param(compile_args, "dialect", "postgres", "contains")

            transpile_args = get_args_for_tool(tools, arguments, "transpile_sql_dialect")
            source_ok = check_param(transpile_args, "source", "postgresql", "contains") or \
                        check_param(transpile_args, "source_dialect", "postgresql", "contains") or \
                        check_param(transpile_args, "source", "postgres", "contains")
            target_ok = check_param(transpile_args, "target", "duckdb", "contains") or \
                        check_param(transpile_args, "target_dialect", "duckdb", "contains")

            if id_ok and dialect_ok and source_ok and target_ok:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL", notes="chain correct but dialect params imprecise")

        if chain_count >= 2:
            return make_score("PARTIAL", "PARTIAL", notes=f"{chain_count}/3 chain tools called")

        return make_score("FAIL", "N/A", notes=f"only {chain_count}/3 tools called")


@dataclass
class P23:
    prompt_id: int = 23
    category_code: str = "C5"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_preview = has_tool(tools, "preview_concept_set")
        has_compile = has_tool(tools, "compile_cohort_definition")

        chain_count = sum([has_search, has_preview, has_compile])

        if chain_count == 3 and tools_in_order(tools, ["search_concepts", "preview_concept_set", "compile_cohort_definition"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["hypertension", "blood pressure", "htn"])
            return make_score("PASS", "CORRECT" if kw_ok else "PARTIAL")

        if chain_count >= 2:
            return make_score("PARTIAL", "PARTIAL", notes=f"{chain_count}/3 chain tools called")

        return make_score("FAIL", "N/A", notes="chain not attempted")


@dataclass
class P24:
    prompt_id: int = 24
    category_code: str = "C5"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_schema = has_tool(tools, "get_table_schema")
        has_query = has_tool(tools, "Select_Query")

        if not has_schema or not has_query:
            return make_score("FAIL", "N/A",
                              notes="missing schema lookup or query")

        schema_args = get_args_for_tool(tools, arguments, "get_table_schema")
        table_ok = check_param(schema_args, "table_name", "condition", "contains") or \
                   check_param(schema_args, "table", "condition", "contains")

        query_args = get_args_for_tool(tools, arguments, "Select_Query")
        sql_ok = check_sql_contains(query_args, ["condition_concept_id"]) or \
                 check_sql_contains(query_args, ["group by"]) or \
                 check_sql_contains(query_args, ["limit", "10"])

        if table_ok and sql_ok:
            return make_score("PASS", "CORRECT")

        return make_score("PARTIAL", "PARTIAL",
                          notes=f"schema_table={'ok' if table_ok else 'wrong'}, sql={'ok' if sql_ok else 'weak'}")


# ── C6: Graceful Degradation ────────────────────────────────────────────


@dataclass
class P25:
    prompt_id: int = 25
    category_code: str = "C6"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "get_phenotype"):
            return make_score("FAIL", "N/A", notes="no tool call attempted")

        args = get_args_for_tool(tools, arguments, "get_phenotype")
        id_ok = check_param(args, "id", 99999, "equals") or check_param(args, "phenotype_id", 99999, "equals")

        # Always flag for manual review — text quality matters
        return make_score(
            "PASS" if id_ok else "PARTIAL",
            "N/A",
            needs_review=True,
            notes="C6: verify text reports 'not found' and suggests alternatives",
        )


@dataclass
class P26:
    prompt_id: int = 26
    category_code: str = "C6"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "search_phenotypes"):
            return make_score("FAIL", "N/A", notes="no tool call attempted")

        args = get_args_for_tool(tools, arguments, "search_phenotypes")
        kw_ok = check_keyword_relevance(args, ["quantum", "computing"])

        return make_score(
            "PASS" if kw_ok else "PARTIAL",
            "N/A",
            needs_review=True,
            notes="C6: verify text reports 'no results' without fabrication",
        )


@dataclass
class P27:
    prompt_id: int = 27
    category_code: str = "C6"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        if not has_tool(tools, "Select_Query"):
            return make_score("FAIL", "N/A", notes="refused to attempt or no tool call")

        return make_score(
            "PASS",
            "N/A",
            needs_review=True,
            notes="C6: verify text explains error and suggests recovery (e.g., list_cdm_tables)",
        )


# ── C7: Multi-Faceted Composition ───────────────────────────────────────


@dataclass
class P28:
    prompt_id: int = 28
    category_code: str = "C7"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_concept = has_tool(tools, "get_concept")
        has_phenotype_search = has_tool(tools, "search_phenotypes")
        # Also accept search_concepts as a way to get domain info
        has_concept_alt = has_tool(tools, "search_concepts")

        concept_addressed = has_concept or has_concept_alt
        phenotype_addressed = has_phenotype_search

        if concept_addressed and phenotype_addressed:
            # Check concept IDs
            if has_concept:
                args = get_args_for_tool(tools, arguments, "get_concept")
                has_ids = check_concept_id_in_args(args, 201826) or check_concept_id_in_args(args, 4193704)
            else:
                has_ids = True  # search_concepts is less specific, accept

            return make_score(
                "PASS", "CORRECT" if has_ids else "PARTIAL",
                needs_review=True,
                notes="C7: verify both domains AND phenotypes addressed in response",
            )

        if concept_addressed or phenotype_addressed:
            which = "concept domain" if concept_addressed else "phenotype search"
            return make_score("PARTIAL", "PARTIAL",
                              needs_review=True,
                              notes=f"C7: only {which} dimension addressed")

        return make_score("FAIL", "N/A", notes="no tools called")


@dataclass
class P29:
    prompt_id: int = 29
    category_code: str = "C7"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_patterns = has_tool(tools, "search_query_patterns")
        has_query = has_tool(tools, "Select_Query")

        if has_patterns and has_query:
            search_args = get_args_for_tool(tools, arguments, "search_query_patterns")
            kw_ok = check_keyword_relevance(search_args, ["drug", "cost"])
            return make_score(
                "PASS", "CORRECT" if kw_ok else "PARTIAL",
                needs_review=True,
                notes="C7: verify both library AND database results compared",
            )

        if has_patterns or has_query:
            which = "library" if has_patterns else "database"
            return make_score("PARTIAL", "PARTIAL",
                              needs_review=True,
                              notes=f"C7: only {which} source consulted")

        return make_score("FAIL", "N/A", notes="no tools called")


@dataclass
class P30:
    prompt_id: int = 30
    category_code: str = "C7"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        phase1 = has_tool(tools, "search_concepts")
        phase2 = has_tool(tools, "search_phenotypes")
        phase3 = has_tool(tools, "get_phenotype") and has_any_tool(
            tools, ["analyze_cohort_complexity", "cohort_dry_run"]
        )

        phases_completed = sum([phase1, phase2, phase3])

        if phases_completed == 3:
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["kidney", "ckd", "renal", "chronic kidney"])
            return make_score(
                "PASS", "CORRECT" if kw_ok else "PARTIAL",
                needs_review=True,
                notes="C7: verify all 3 phases (concepts, phenotypes, analysis) completed",
            )

        if phases_completed == 2:
            return make_score("PARTIAL", "PARTIAL",
                              needs_review=True,
                              notes=f"C7: {phases_completed}/3 phases completed")

        return make_score("FAIL", "N/A",
                          notes=f"only {phases_completed}/3 phases completed")


# ── C8: Cohort Construction ────────────────────────────────────────────


@dataclass
class P31:
    prompt_id: int = 31
    category_code: str = "C8"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_build = has_tool(tools, "build_cohort_definition")

        if has_search and has_build and tools_in_order(tools, ["search_concepts", "build_cohort_definition"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args, ["diabetes", "type 2", "t2dm"])

            build_args = get_args_for_tool(tools, arguments, "build_cohort_definition")
            has_spec = check_param(build_args, "spec_json", check_type="exists")

            if kw_ok and has_spec:
                return make_score("PASS", "CORRECT")
            return make_score("PASS", "PARTIAL",
                              notes="chain correct but keyword/spec issues")

        if has_build and not has_search:
            return make_score("PARTIAL", "PARTIAL",
                              notes="build_cohort_definition called without vocab grounding")

        if has_search and not has_build:
            return make_score("FAIL", "N/A",
                              notes="search_concepts called but build_cohort_definition not used")

        return make_score("FAIL", "N/A", notes="neither tool called")


@dataclass
class P32:
    prompt_id: int = 32
    category_code: str = "C8"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_build = has_tool(tools, "build_cohort_definition")

        if has_search and has_build and tools_in_order(tools, ["search_concepts", "build_cohort_definition"]):
            search_args = get_args_for_tool(tools, arguments, "search_concepts")
            kw_ok = check_keyword_relevance(search_args,
                                            ["hypertension", "kidney", "ckd", "renal", "blood pressure"])

            build_args = get_args_for_tool(tools, arguments, "build_cohort_definition")
            has_spec = check_param(build_args, "spec_json", check_type="exists")

            # Check that the spec mentions exclusion_criteria
            spec_has_exclusion = False
            if has_spec and build_args:
                spec_str = str(build_args.get("spec_json", ""))
                spec_has_exclusion = "exclusion" in spec_str.lower()

            if kw_ok and has_spec and spec_has_exclusion:
                return make_score("PASS", "CORRECT")
            if kw_ok and has_spec:
                return make_score("PASS", "PARTIAL",
                                  notes="chain correct but exclusion_criteria may be missing")
            return make_score("PASS", "PARTIAL", notes="chain correct but param issues")

        if has_build and not has_search:
            return make_score("PARTIAL", "PARTIAL",
                              notes="build_cohort_definition called without vocab grounding")

        if has_search and not has_build:
            return make_score("FAIL", "N/A",
                              notes="search_concepts called but build_cohort_definition not used")

        return make_score("FAIL", "N/A", notes="neither tool called")


@dataclass
class P33:
    prompt_id: int = 33
    category_code: str = "C8"

    def evaluate(self, tools: list[str], arguments: list[dict]) -> dict:
        has_search = has_tool(tools, "search_concepts")
        has_build = has_tool(tools, "build_cohort_definition")

        if has_search and has_build and tools_in_order(tools, ["search_concepts", "build_cohort_definition"]):
            # Should search for both T2DM and Metformin concepts
            search_count = count_tool(tools, "search_concepts")

            build_args = get_args_for_tool(tools, arguments, "build_cohort_definition")
            has_spec = check_param(build_args, "spec_json", check_type="exists")

            # Check spec contains inclusion_rules and demographic indicators
            spec_has_inclusion = False
            spec_has_demographic = False
            if has_spec and build_args:
                spec_str = str(build_args.get("spec_json", ""))
                spec_has_inclusion = "inclusion" in spec_str.lower()
                spec_has_demographic = ("age" in spec_str.lower() or "demographic" in spec_str.lower())

            if has_spec and spec_has_inclusion and spec_has_demographic:
                return make_score("PASS", "CORRECT")
            if has_spec and spec_has_inclusion:
                return make_score("PASS", "PARTIAL",
                                  notes="inclusion rules present but demographics may be missing")
            if has_spec:
                return make_score("PASS", "PARTIAL",
                                  notes="chain correct but inclusion/demographic fields may be missing")
            return make_score("PASS", "PARTIAL", notes="chain correct but spec issues")

        if has_build and not has_search:
            return make_score("PARTIAL", "PARTIAL",
                              notes="build_cohort_definition called without vocab grounding")

        if has_search and not has_build:
            return make_score("FAIL", "N/A",
                              notes="search_concepts called but build_cohort_definition not used")

        return make_score("FAIL", "N/A", notes="neither tool called")


# ── Rule registry ────────────────────────────────────────────────────────

RULES: dict[int, PromptRule] = {
    1: P01(), 2: P02(), 3: P03(), 4: P04(), 5: P05(), 6: P06(),
    7: P07(), 8: P08(), 9: P09(), 10: P10(),
    11: P11(), 12: P12(), 13: P13(), 14: P14(),
    15: P15(), 16: P16(), 17: P17(), 18: P18(), 19: P19(), 20: P20(),
    21: P21(), 22: P22(), 23: P23(), 24: P24(),
    25: P25(), 26: P26(), 27: P27(),
    28: P28(), 29: P29(), 30: P30(),
    31: P31(), 32: P32(), 33: P33(),
}


def get_rule(prompt_id: int) -> PromptRule | None:
    """Look up the scoring rule for a prompt ID."""
    return RULES.get(prompt_id)
