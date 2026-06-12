"""Generic scoring helper functions for the OHDSI Agent evaluation codebook.

These functions operate on parsed tool call data (tool names and argument dicts)
extracted from evaluation result CSVs. They are used by codebook.py rules.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ── Tool presence checks ─────────────────────────────────────────────────

def has_tool(tools: list[str], tool_name: str) -> bool:
    """Check if a tool appears anywhere in the call list."""
    return tool_name in tools


def has_any_tool(tools: list[str], tool_names: list[str]) -> bool:
    """Check if any of the given tools appears in the call list."""
    return any(t in tools for t in tool_names)


def has_all_tools(tools: list[str], tool_names: list[str]) -> bool:
    """Check if all of the given tools appear in the call list."""
    return all(t in tools for t in tool_names)


def tools_in_order(tools: list[str], sequence: list[str]) -> bool:
    """Check if the given tools appear in the specified order (not necessarily contiguous).

    Example: tools_in_order(["search_concepts", "get_concept", "compile"], ["search_concepts", "compile"])
    returns True because search_concepts appears before compile.
    """
    idx = 0
    for t in tools:
        if idx < len(sequence) and t == sequence[idx]:
            idx += 1
    return idx == len(sequence)


def count_tool(tools: list[str], tool_name: str) -> int:
    """Count occurrences of a tool in the call list."""
    return tools.count(tool_name)


def first_tool_is(tools: list[str], tool_name: str) -> bool:
    """Check if the first tool called matches."""
    return len(tools) > 0 and tools[0] == tool_name


def only_tool_before(tools: list[str], target: str, unwanted: list[str]) -> bool:
    """Check that none of the unwanted tools appear before the target tool."""
    for t in tools:
        if t == target:
            return True
        if t in unwanted:
            return False
    return False  # target not found


# ── Argument checks ──────────────────────────────────────────────────────

def get_args_for_tool(
    tools: list[str],
    arguments: list[dict],
    tool_name: str,
    occurrence: int = 0,
) -> dict | None:
    """Get the arguments dict for the Nth occurrence of a tool.

    Returns None if the tool isn't found or occurrence index is out of range.
    """
    found = 0
    for t, args in zip(tools, arguments):
        if t == tool_name:
            if found == occurrence:
                return args
            found += 1
    return None


def check_param(
    args: dict | None,
    param_name: str,
    expected: Any = None,
    check_type: str = "exists",
) -> bool:
    """Check a parameter in a tool's arguments.

    check_type options:
        "exists"   - param_name is present in args
        "equals"   - args[param_name] == expected
        "contains" - expected is a substring of str(args[param_name]) (case-insensitive)
        "in_list"  - expected value is in args[param_name] (list)
        "truthy"   - args[param_name] is truthy
    """
    if args is None:
        return False

    val = args.get(param_name)
    if val is None:
        return False

    if check_type == "exists":
        return True
    elif check_type == "equals":
        return val == expected
    elif check_type == "contains":
        return str(expected).lower() in str(val).lower()
    elif check_type == "in_list":
        if isinstance(val, list):
            return expected in val
        return False
    elif check_type == "truthy":
        return bool(val)
    return False


def check_concept_id_in_args(
    args: dict | None,
    expected_id: int,
    param_names: list[str] | None = None,
) -> bool:
    """Check if a concept_id appears in the arguments under common param names.

    Searches through param_names (default: concept_id, concept_ids, conceptId, conceptIds)
    and checks both scalar and list values.
    """
    if args is None:
        return False

    if param_names is None:
        param_names = ["concept_id", "concept_ids", "conceptId", "conceptIds", "id", "ids"]

    for pname in param_names:
        val = args.get(pname)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            if int(val) == expected_id:
                return True
        elif isinstance(val, list):
            if expected_id in [int(v) for v in val if _is_numeric(v)]:
                return True
        elif isinstance(val, str):
            if str(expected_id) in val:
                return True
    return False


def check_keyword_relevance(
    args: dict | None,
    keywords: list[str],
    param_names: list[str] | None = None,
) -> bool:
    """Check if any keyword appears in search-related argument values.

    Searches param_names (default: query, search, keyword, name, term, text).
    Case-insensitive partial match.
    """
    if args is None:
        return False

    if param_names is None:
        param_names = ["query", "search", "keyword", "name", "term", "text",
                       "search_term", "pattern", "condition"]

    for pname in param_names:
        val = args.get(pname)
        if val is None:
            continue
        val_lower = str(val).lower()
        if any(kw.lower() in val_lower for kw in keywords):
            return True

    return False


def check_sql_contains(
    args: dict | None,
    patterns: list[str],
    param_names: list[str] | None = None,
) -> bool:
    """Check if SQL in arguments contains expected patterns (case-insensitive).

    Searches param_names (default: sql, query, statement).
    """
    if args is None:
        return False

    if param_names is None:
        param_names = ["sql", "query", "statement"]

    for pname in param_names:
        val = args.get(pname)
        if val is None:
            continue
        val_lower = str(val).lower()
        if all(p.lower() in val_lower for p in patterns):
            return True

    return False


# ── Parsing helpers ──────────────────────────────────────────────────────

def parse_tools_called(raw: str) -> list[str]:
    """Parse the pipe-delimited tools_called column into a list of tool names."""
    if not raw or raw.strip() == "":
        return []
    return [t.strip() for t in raw.split("|") if t.strip()]


def parse_tool_arguments(raw: str) -> list[dict]:
    """Parse the JSON tool_arguments column into a list of dicts."""
    if not raw or raw.strip() == "":
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [d if isinstance(d, dict) else {} for d in parsed]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_tool_results(raw: str) -> list[dict]:
    """Parse the JSON tool_results column into a list of {"name", "result"} dicts."""
    if not raw or raw.strip() == "":
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [d if isinstance(d, dict) else {} for d in parsed]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def get_result_for_tool(
    tool_results: list[dict],
    tool_name: str,
    occurrence: int = -1,
) -> str | None:
    """Get the result string for the Nth occurrence of a tool result.

    Default occurrence=-1 returns the LAST occurrence (most useful for
    compile_cohort_definition which may be called multiple times).
    Returns None if the tool isn't found.
    """
    matches = [tr for tr in tool_results if tr.get("name") == tool_name]
    if not matches:
        return None
    try:
        return matches[occurrence].get("result")
    except IndexError:
        return None


def _is_numeric(val: Any) -> bool:
    """Check if a value can be converted to int."""
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


# ── Scoring result types ─────────────────────────────────────────────────

TOOL_SCORES = ("PASS", "PARTIAL", "FAIL")
PARAM_SCORES = ("CORRECT", "PARTIAL", "INCORRECT", "N/A")
EXECUTION_SCORES = ("VALID", "INVALID", "ERROR", "N/A")

# ── Failure mode taxonomy ────────────────────────────────────────────────

FAILURE_MODES = {
    "TOOL_OMISSION": "Required tool never called",
    "WRONG_TOOL": "Called a semantically different tool",
    "HALLUCINATION": "Fabricated data without tool call or fabricated tool results",
    "PARAM_ERROR": "Right tool, wrong arguments",
    "CHAIN_BREAK": "Multi-step chain started but output didn't flow to next step",
    "TIMEOUT": "300s limit reached",
    "WRONG_DIRECTION": "Ancestors vs. descendants confusion",
    "OVER_BROAD": "Used a broader tool when specific one exists",
    "INFO_OMISSION": "Tool called correctly but response omits key information",
    "REFUSAL": "Agent refused to call a tool that should have been called",
    "SQL_ERROR": "Agent's SQL was syntactically invalid or referenced wrong schema",
}

# Prompts that involve SQL execution (Tier A execution validity applies)
SQL_GENERATING_PROMPTS = {15, 19, 20, 21, 22, 23, 24, 27, 29, 30, 31, 32, 33}

# Prompts with gold-standard cohort comparison (Tier B Jaccard/F1)
GOLD_STANDARD_PROMPTS = {15, 19, 21, 24, 31, 32, 33}


def classify_failure(result: str, tools: list[str], arguments: list[dict],
                     expected_tools: list[str], errors: str = "") -> list[str]:
    """Automatically classify failure modes based on scoring data.

    Returns a list of applicable failure mode codes.
    """
    modes: list[str] = []

    if result not in ("FAIL", "PARTIAL"):
        return modes

    # Timeout
    if "timeout" in errors.lower():
        modes.append("TIMEOUT")
        return modes

    # No tools called at all
    if not tools:
        if expected_tools:
            modes.append("TOOL_OMISSION")
        return modes

    # Check for wrong tool selection
    expected_set = set(expected_tools)
    called_set = set(tools)
    if expected_set and not expected_set.intersection(called_set):
        modes.append("WRONG_TOOL")

    # Check for tool omission (some expected tools missing)
    missing = expected_set - called_set
    if missing and called_set.intersection(expected_set):
        modes.append("TOOL_OMISSION")

    # Check hierarchy direction confusion
    hierarchy_tools = {"get_concept_ancestors", "get_concept_descendants"}
    if called_set.intersection(hierarchy_tools) and expected_set.intersection(hierarchy_tools):
        if called_set.intersection(hierarchy_tools) != expected_set.intersection(hierarchy_tools):
            modes.append("WRONG_DIRECTION")

    # Over-broad tool
    broad_narrow = {
        "list_cdm_tables": "get_table_schema",
        "search_concepts": "get_concept",
        "get_concept_relationships": "get_concept_descendants",
    }
    for broad, narrow in broad_narrow.items():
        if broad in called_set and narrow in expected_set and narrow not in called_set:
            modes.append("OVER_BROAD")
            break

    return modes


def make_score(
    tool_selection: str,
    parameter_correctness: str,
    needs_review: bool = False,
    notes: str = "",
    failure_modes: list[str] | None = None,
) -> dict:
    """Create a standardized score result dict."""
    return {
        "result": tool_selection,
        "parameters_correct": parameter_correctness,
        "needs_review": needs_review,
        "auto_notes": notes,
        "failure_modes": failure_modes or [],
    }
