"""Analyze multi-model routing evaluation results and produce JAMIA-ready tables.

Reads all CSV files from results/, merges them, and outputs:
  1. Model comparison matrix (30 prompts x N models)
  2. Pass rate by model with 95% Bayesian Beta-Binomial CIs
  3. Pass rate by capability category (C1-C7)
  4. Latency comparison by model
  5. Cross-server chain success rates (C4)
  6. Parameter correctness rates
  7. JAMIA-ready markdown tables

Usage (use `--with scipy` for the Fisher's exact table and exact Beta credible intervals):
    uv run --with scipy python analyze_results.py
    uv run --with scipy python analyze_results.py --output report.md
"""

from __future__ import annotations

import argparse
import csv
import math

csv.field_size_limit(10_000_000)  # tool_arguments or text_response can exceed 128KB default
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

# Category definitions
CATEGORY_NAMES = {
    "C1": "Single Tool Selection",
    "C2": "Tool Disambiguation",
    "C3": "Intra-Server Chaining",
    "C4": "Cross-Server Chaining",
    "C5": "Parameter Construction",
    "C6": "Graceful Degradation",
    "C7": "Multi-Faceted Composition",
    "C8": "Cohort Construction",
}

CATEGORY_PROMPT_COUNTS = {
    "C1": 6, "C2": 4, "C3": 4, "C4": 6, "C5": 4, "C6": 3, "C7": 3, "C8": 3,
}

# Cross-server category for dedicated analysis
CROSS_SERVER_CATEGORY = "C4"

# ── Study vs. pre-study model partition ──────────────────────────────────
# The STUDY evaluated FOUR models. DeepSeek V3 was a PRE-STUDY feasibility build
# (open condition only, runs truncated by API failures) used to assess whether a
# third-party cloud model could be included. It is NOT part of the study and is
# EXCLUDED from every study statistic; it is reported separately for transparency.
STUDY_MODELS = {
    "claude/claude-sonnet-4-20250514",
    "claude/claude-haiku-4-5-20251001",
    "ollama/qwen3:14b",
    "ollama/qwen3:8b",
}


# ── Bayesian CI ──────────────────────────────────────────────────────────

def beta_binomial_ci(
    successes: int, trials: int,
    alpha_prior: float = 1.0, beta_prior: float = 1.0,
    credible: float = 0.95,
) -> tuple[float, float]:
    """Compute a Bayesian Beta-Binomial credible interval.

    Uses the Beta(alpha_prior + successes, beta_prior + failures) posterior.
    Returns (lower, upper) bounds as proportions.

    Default: uniform prior Beta(1, 1). For Jeffreys prior use (0.5, 0.5).
    """
    if trials == 0:
        return (0.0, 1.0)

    a = alpha_prior + successes
    b = beta_prior + (trials - successes)

    # Use scipy if available, otherwise fall back to normal approximation
    try:
        from scipy.stats import beta as beta_dist
        tail = (1 - credible) / 2
        lo = beta_dist.ppf(tail, a, b)
        hi = beta_dist.ppf(1 - tail, a, b)
        return (round(lo, 4), round(hi, 4))
    except ImportError:
        # Normal approximation to Beta posterior
        mean = a / (a + b)
        var = (a * b) / ((a + b) ** 2 * (a + b + 1))
        sd = math.sqrt(var)
        z = 1.96  # ~95%
        lo = max(0.0, mean - z * sd)
        hi = min(1.0, mean + z * sd)
        return (round(lo, 4), round(hi, 4))


# ── Data loading ─────────────────────────────────────────────────────────

def load_all_results(results_dir: Path) -> list[dict]:
    """Load and merge all CSV result files recursively."""
    rows = []
    skip = {"result_provenance.csv", "flagged_for_review.csv"}
    csv_files = sorted(results_dir.rglob("*.csv"))

    loaded = 0
    for p in csv_files:
        if p.name in skip or p.name.startswith("."):
            continue
        # Skip archived results to avoid double-counting
        if "archive" in p.parts:
            continue
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            file_rows = list(reader)
            rows.extend(file_rows)
            loaded += 1
            print(f"  {p.relative_to(results_dir)}: {len(file_rows)} rows")

    print(f"Loaded {loaded} result files")
    return rows


def model_key(row: dict) -> str:
    """Return a display key like 'ollama/qwen3:8b'."""
    return f"{row['provider']}/{row['model']}"


def split_study_prestudy(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition rows into the four study models vs. the pre-study pilot.

    All study statistics are computed over the study rows only; the pre-study
    feasibility build (DeepSeek V3) is reported separately and never folded into
    a study aggregate or comparison.
    """
    study = [r for r in rows if model_key(r) in STUDY_MODELS]
    prestudy = [r for r in rows if model_key(r) not in STUDY_MODELS]
    return study, prestudy


def prestudy_pilot_section(prestudy_rows: list[dict]) -> str:
    """Report the pre-study feasibility build separately (excluded from study stats)."""
    if not prestudy_rows:
        return ""
    lines = [
        "## Pre-study feasibility build (EXCLUDED from all study statistics)",
        "",
        "DeepSeek V3 was run as a *pre-study feasibility build* to assess whether a "
        "third-party cloud model could be included. It ran under the open condition "
        "only, with runs truncated by API connection failures. It is **not** part of "
        "the four-model study and is excluded from every table above.",
        "",
        "| Model (pre-study) | n | PASS | Pass % |",
        "|:--|--:|--:|--:|",
    ]
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in prestudy_rows:
        by_model[model_key(r)].append(r)
    for mk in sorted(by_model):
        n, p, pct = pass_rate(by_model[mk])
        lines.append(f"| {mk} | {n} | {p} | {pct}% |")
    return "\n".join(lines)


# ── Statistics helpers ───────────────────────────────────────────────────

def pass_rate(rows: list[dict]) -> tuple[int, int, float]:
    """Count scored rows, passes, and compute rate."""
    scored = [r for r in rows if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
    if not scored:
        return 0, 0, 0.0
    passes = sum(1 for r in scored if r["result"] == "PASS")
    return len(scored), passes, round(passes / len(scored) * 100, 1)


def partial_rate(rows: list[dict]) -> float:
    """Fraction scored PASS or PARTIAL."""
    scored = [r for r in rows if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
    if not scored:
        return 0.0
    ok = sum(1 for r in scored if r["result"] in ("PASS", "PARTIAL"))
    return round(ok / len(scored) * 100, 1)


def avg_latency(rows: list[dict]) -> float:
    """Mean latency in seconds across rows with numeric latency."""
    vals = []
    for r in rows:
        try:
            v = float(r.get("latency_sec", 0))
            if v > 0:
                vals.append(v)
        except (ValueError, TypeError):
            continue
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def median_latency(rows: list[dict]) -> float:
    """Median latency in seconds."""
    vals = sorted(
        float(r["latency_sec"])
        for r in rows
        if r.get("latency_sec") and float(r.get("latency_sec", 0)) > 0
    )
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2 == 0:
        return round((vals[mid - 1] + vals[mid]) / 2, 2)
    return round(vals[mid], 2)


# ── Report generators ───────────────────────────────────────────────────

def table_pass_rate_by_model(rows: list[dict]) -> str:
    """Table 1: Overall pass rate by model with Bayesian 95% CIs."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[model_key(r)].append(r)

    lines = [
        "## Table 1: Pass Rate by Model (95% Bayesian CI)",
        "",
        "| Model | n | PASS | PARTIAL | FAIL | Pass % | 95% CI | Pass+Partial % |",
        "|:------|--:|-----:|--------:|-----:|-------:|:------:|---------------:|",
    ]

    for mk in sorted(by_model):
        model_rows = by_model[mk]
        scored = [r for r in model_rows if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
        n = len(scored)
        p = sum(1 for r in scored if r["result"] == "PASS")
        pt = sum(1 for r in scored if r["result"] == "PARTIAL")
        f = sum(1 for r in scored if r["result"] == "FAIL")
        pct = round(p / n * 100, 1) if n else 0
        pp_pct = round((p + pt) / n * 100, 1) if n else 0
        lo, hi = beta_binomial_ci(p, n)
        ci_str = f"[{lo:.1%}, {hi:.1%}]"
        lines.append(f"| {mk} | {n} | {p} | {pt} | {f} | {pct}% | {ci_str} | {pp_pct}% |")

    return "\n".join(lines)


def table_pass_rate_by_category(rows: list[dict]) -> str:
    """Table 2: Pass rate by capability category (C1-C7)."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cat = r.get("category_code", "?")
        by_cat[cat].append(r)

    lines = [
        "## Table 2: Pass Rate by Capability Category",
        "",
        "| Category | Name | Prompts | Scored | PASS | Pass % | 95% CI |",
        "|:---------|:-----|--------:|-------:|-----:|-------:|:------:|",
    ]

    for cat in sorted(by_cat):
        cat_rows = by_cat[cat]
        name = CATEGORY_NAMES.get(cat, cat)
        prompt_ids = sorted(set(int(r["prompt_id"]) for r in cat_rows))
        n_prompts = len(prompt_ids)
        scored = [r for r in cat_rows if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
        n = len(scored)
        p = sum(1 for r in scored if r["result"] == "PASS")
        pct = round(p / n * 100, 1) if n else 0
        lo, hi = beta_binomial_ci(p, n)
        ci_str = f"[{lo:.1%}, {hi:.1%}]"
        lines.append(f"| {cat} | {name} | {n_prompts} | {n} | {p} | {pct}% | {ci_str} |")

    return "\n".join(lines)


def table_model_comparison_matrix(rows: list[dict]) -> str:
    """Table 3: Prompt x Model matrix with PASS/PARTIAL/FAIL.

    When multiple runs exist for the same (prompt, model), shows the pass rate
    as a fraction (e.g., '2/3') instead of a single result.
    """
    models = sorted(set(model_key(r) for r in rows))
    prompts = sorted(set(int(r["prompt_id"]) for r in rows))

    # Build lookup: (prompt_id, model) → list of results
    lookup: dict[tuple[int, str], list[str]] = defaultdict(list)
    for r in rows:
        pid = int(r["prompt_id"])
        mk = model_key(r)
        result = r.get("result", "")
        if result:
            lookup[(pid, mk)].append(result)

    # Map prompt to category
    prompt_cat: dict[int, str] = {}
    for r in rows:
        prompt_cat[int(r["prompt_id"])] = r.get("category_code", "?")

    # Header
    model_headers = " | ".join(models)
    lines = [
        "## Table 3: Model Comparison Matrix",
        "",
        f"| P# | Cat | {model_headers} |",
        f"|---:|:----|{' | '.join(['---:'] * len(models))} |",
    ]

    for pid in prompts:
        cat = prompt_cat.get(pid, "?")
        cells = []
        for mk in models:
            results = lookup.get((pid, mk), [])
            if not results:
                cells.append("-")
            elif len(results) == 1:
                cells.append(results[0])
            else:
                # Multiple runs: show pass count / total
                passes = sum(1 for r in results if r == "PASS")
                cells.append(f"{passes}/{len(results)}")
        lines.append(f"| {pid} | {cat} | {' | '.join(cells)} |")

    return "\n".join(lines)


def table_latency_by_model(rows: list[dict]) -> str:
    """Table 4: Latency statistics by model."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[model_key(r)].append(r)

    lines = [
        "## Table 4: Latency by Model (seconds)",
        "",
        "| Model | Mean | Median | Min | Max |",
        "|:------|-----:|-------:|----:|----:|",
    ]

    for mk in sorted(by_model):
        model_rows = by_model[mk]
        vals = sorted(
            float(r["latency_sec"])
            for r in model_rows
            if r.get("latency_sec") and float(r.get("latency_sec", 0)) > 0
        )
        if vals:
            mean = round(sum(vals) / len(vals), 2)
            med = median_latency(model_rows)
            mn = round(min(vals), 2)
            mx = round(max(vals), 2)
            lines.append(f"| {mk} | {mean} | {med} | {mn} | {mx} |")
        else:
            lines.append(f"| {mk} | - | - | - | - |")

    return "\n".join(lines)


def table_cross_server_chains(rows: list[dict]) -> str:
    """Table 5: Cross-server chain (C4) success rates by prompt and model."""
    c4_rows = [r for r in rows if r.get("category_code") == CROSS_SERVER_CATEGORY]
    if not c4_rows:
        return "## Table 5: Cross-Server Chain Success\n\nNo C4 results found."

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in c4_rows:
        by_model[model_key(r)].append(r)

    models = sorted(by_model)
    prompts = sorted(set(int(r["prompt_id"]) for r in c4_rows))

    # Build lookup
    lookup: dict[tuple[int, str], str] = {}
    for r in c4_rows:
        lookup[(int(r["prompt_id"]), model_key(r))] = r.get("result", "-")

    lines = [
        "## Table 5: Cross-Server Chain Success (C4)",
        "",
    ]

    # Per-model summary
    lines.extend([
        "| Model | n | PASS | Pass % | 95% CI |",
        "|:------|--:|-----:|-------:|:------:|",
    ])

    for mk in models:
        scored = [r for r in by_model[mk] if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
        n = len(scored)
        p = sum(1 for r in scored if r["result"] == "PASS")
        pct = round(p / n * 100, 1) if n else 0
        lo, hi = beta_binomial_ci(p, n)
        ci_str = f"[{lo:.1%}, {hi:.1%}]"
        lines.append(f"| {mk} | {n} | {p} | {pct}% | {ci_str} |")

    return "\n".join(lines)


def table_failure_modes(rows: list[dict]) -> str:
    """Table: Failure mode distribution by model."""
    from collections import Counter

    by_model: dict[str, Counter] = defaultdict(Counter)
    all_modes: Counter = Counter()

    for r in rows:
        modes = r.get("failure_mode", "")
        if not modes:
            continue
        mk = model_key(r)
        for m in modes.split("|"):
            m = m.strip()
            if m:
                by_model[mk][m] += 1
                all_modes[m] += 1

    if not all_modes:
        return "## Table: Failure Mode Distribution\n\nNo failure modes recorded."

    mode_names = [m for m, _ in all_modes.most_common()]
    models = sorted(by_model)

    mode_headers = " | ".join(mode_names)
    lines = [
        "## Table: Failure Mode Distribution by Model",
        "",
        f"| Model | {mode_headers} | Total |",
        f"|:------|{' | '.join(['---:'] * len(mode_names))} | ---: |",
    ]

    for mk in models:
        counts = by_model[mk]
        cells = [str(counts.get(m, 0)) for m in mode_names]
        total = sum(counts.values())
        lines.append(f"| {mk} | {' | '.join(cells)} | {total} |")

    # Totals row
    total_cells = [str(all_modes[m]) for m in mode_names]
    lines.append(f"| **Total** | {' | '.join(total_cells)} | {sum(all_modes.values())} |")

    return "\n".join(lines)


def _fisher_p(a: int, b: int, c: int, d: int):
    """Two-sided Fisher's exact p-value for the 2x2 table [[a, b], [c, d]].

    Returns the p-value, or None if scipy is unavailable (run with
    `uv run --with scipy` to enable). Same dependency handling as Table 11.
    """
    try:
        from scipy.stats import fisher_exact
    except ImportError:
        return None
    _, p = fisher_exact([[a, b], [c, d]])
    return p


def table_open_vs_guided(rows: list[dict]) -> str:
    """Table: Open vs Guided condition comparison by model (guided prompts only)."""
    # Guided prompts are P19, P21, P31, P32, P33
    guided_prompt_ids = {"19", "21", "31", "32", "33"}

    # Only include rows for prompts that have both conditions
    relevant = [r for r in rows if str(r.get("prompt_id", "")) in guided_prompt_ids
                and r.get("result") in ("PASS", "PARTIAL", "FAIL")]

    if not relevant:
        return "## Table: Open vs Guided Condition Comparison\n\nNo guided-condition data found."

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in relevant:
        mk = model_key(r)
        cond = r.get("condition", "open")
        by_model[mk][cond].append(r)

    lines = [
        "## Table: Open vs Guided Condition Comparison",
        "",
        "Guided prompts (P19, P21, P31-P33): raw SQL hidden, forcing structured tool paths.",
        "",
        "| Model | Open Pass % (n) | Guided Pass % (n) | Delta | p (Fisher) |",
        "|:------|----------------:|-------------------:|------:|-----------:|",
    ]

    for mk in sorted(by_model):
        open_rows = by_model[mk].get("open", [])
        guided_rows = by_model[mk].get("guided", [])

        if open_rows:
            op = sum(1 for r in open_rows if r["result"] == "PASS")
            o_pct = round(op / len(open_rows) * 100, 1)
            o_str = f"{o_pct}% ({op}/{len(open_rows)})"
        else:
            o_pct = 0
            o_str = "-"

        if guided_rows:
            gp = sum(1 for r in guided_rows if r["result"] == "PASS")
            g_pct = round(gp / len(guided_rows) * 100, 1)
            g_str = f"{g_pct}% ({gp}/{len(guided_rows)})"
        else:
            g_pct = 0
            g_str = "-"

        if open_rows and guided_rows:
            delta = round(g_pct - o_pct, 1)
            d_str = f"{delta:+.1f}pp"
            o_fail = len(open_rows) - op
            g_fail = len(guided_rows) - gp
            pv = _fisher_p(op, o_fail, gp, g_fail)
            p_str = f"{pv:.4f}" if pv is not None else "(scipy)"
        else:
            d_str = "-"
            p_str = "-"

        lines.append(f"| {mk} | {o_str} | {g_str} | {d_str} | {p_str} |")

    return "\n".join(lines)


def table_category_contrasts(rows: list[dict]) -> str:
    """Table 12: Fisher's exact test of C5 (the lowest-performing category) against
    every other capability category's pass rate."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("result") in ("PASS", "PARTIAL", "FAIL"):
            by_cat[r.get("category_code", "?")].append(r)

    def pf(cat: str) -> tuple[int, int, int]:
        rs = by_cat.get(cat, [])
        p = sum(1 for r in rs if r["result"] == "PASS")
        return p, len(rs) - p, len(rs)

    if "C5" not in by_cat:
        return "## Table 12: Category Contrasts vs C5\n\nNo C5 data."

    c5_pass, c5_fail, c5_n = pf("C5")
    c5_pct = round(c5_pass / c5_n * 100, 1) if c5_n else 0
    lines = [
        "## Table 12: Category Contrasts (Fisher's Exact Test vs C5)",
        "",
        "C5 (Parameter Construction) is the lowest-performing category; each row tests "
        "its pass rate against another category.",
        "",
        "| Category | Pass % | C5 Pass % | p-value |",
        "|:---------|-------:|----------:|--------:|",
    ]
    for cat in [f"C{i}" for i in range(1, 9)]:
        if cat == "C5" or cat not in by_cat:
            continue
        cp, cf, cn = pf(cat)
        cpct = round(cp / cn * 100, 1) if cn else 0
        pv = _fisher_p(cp, cf, c5_pass, c5_fail)
        p_str = f"{pv:.2e}" if pv is not None else "(scipy)"
        lines.append(f"| {cat} ({CATEGORY_NAMES.get(cat, cat)}) | {cpct}% | {c5_pct}% | {p_str} |")
    return "\n".join(lines)


def table_pass_rate_by_model_temperature(rows: list[dict]) -> str:
    """Table 7: Pass rate by model stratified by temperature."""
    temps = sorted(set(r.get("temperature", "") for r in rows if r.get("temperature", "")))
    if not temps:
        return "## Table 7: Pass Rate by Model × Temperature\n\nNo temperature data found."

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[model_key(r)].append(r)

    temp_headers = " | ".join(f"T={t}" for t in temps)
    lines = [
        "## Table 7: Pass Rate by Model × Temperature",
        "",
        f"| Model | {temp_headers} |",
        f"|:------|{' | '.join(['------:'] * len(temps))} |",
    ]

    for mk in sorted(by_model):
        cells = []
        for t in temps:
            t_rows = [r for r in by_model[mk] if r.get("temperature", "") == t
                      and r.get("result") in ("PASS", "PARTIAL", "FAIL")]
            if not t_rows:
                cells.append("-")
            else:
                p = sum(1 for r in t_rows if r["result"] == "PASS")
                n = len(t_rows)
                pct = round(p / n * 100, 1)
                cells.append(f"{pct}% ({p}/{n})")
        lines.append(f"| {mk} | {' | '.join(cells)} |")

    return "\n".join(lines)


def table_pass_rate_by_category_temperature(rows: list[dict]) -> str:
    """Table 8: Pass rate by category stratified by temperature."""
    temps = sorted(set(r.get("temperature", "") for r in rows if r.get("temperature", "")))
    if not temps:
        return "## Table 8: Pass Rate by Category × Temperature\n\nNo temperature data found."

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r.get("category_code", "?")].append(r)

    temp_headers = " | ".join(f"T={t}" for t in temps)
    lines = [
        "## Table 8: Pass Rate by Category × Temperature",
        "",
        f"| Category | Name | {temp_headers} |",
        f"|:---------|:-----|{' | '.join(['------:'] * len(temps))} |",
    ]

    for cat in sorted(by_cat):
        name = CATEGORY_NAMES.get(cat, cat)
        cells = []
        for t in temps:
            t_rows = [r for r in by_cat[cat] if r.get("temperature", "") == t
                      and r.get("result") in ("PASS", "PARTIAL", "FAIL")]
            if not t_rows:
                cells.append("-")
            else:
                p = sum(1 for r in t_rows if r["result"] == "PASS")
                n = len(t_rows)
                pct = round(p / n * 100, 1)
                cells.append(f"{pct}%")
        lines.append(f"| {cat} | {name} | {' | '.join(cells)} |")

    return "\n".join(lines)


def table_trajectory_diversity(rows: list[dict]) -> str:
    """Table 9: Trajectory diversity — unique tool-call sequences per prompt-model-temperature."""
    # Group by (model, prompt, temperature) → list of tool sequences
    trajectories: dict[tuple[str, int, str], list[str]] = defaultdict(list)
    for r in rows:
        mk = model_key(r)
        pid = int(r.get("prompt_id", 0))
        temp = r.get("temperature", "")
        seq = r.get("tools_called", "").strip()
        trajectories[(mk, pid, temp)].append(seq)

    if not trajectories:
        return "## Table 9: Trajectory Diversity\n\nNo data."

    # Aggregate: per model-temperature, compute mean unique sequences across prompts
    model_temp_diversity: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (mk, pid, temp), seqs in trajectories.items():
        n_unique = len(set(seqs))
        n_total = len(seqs)
        diversity = n_unique / n_total if n_total > 0 else 0.0
        model_temp_diversity[(mk, temp)].append(diversity)

    temps = sorted(set(t for _, t in model_temp_diversity if t))
    models = sorted(set(mk for mk, _ in model_temp_diversity))

    if not temps:
        return "## Table 9: Trajectory Diversity\n\nNo temperature data found."

    temp_headers = " | ".join(f"T={t}" for t in temps)
    lines = [
        "## Table 9: Trajectory Diversity",
        "",
        "Mean proportion of unique tool-call sequences per prompt (1.0 = all runs identical, "
        "lower = more diverse trajectories).",
        "",
        f"| Model | {temp_headers} |",
        f"|:------|{' | '.join(['------:'] * len(temps))} |",
    ]

    for mk in models:
        cells = []
        for t in temps:
            divs = model_temp_diversity.get((mk, t), [])
            if divs:
                mean_div = round(sum(divs) / len(divs), 3)
                cells.append(f"{mean_div:.3f}")
            else:
                cells.append("-")
        lines.append(f"| {mk} | {' | '.join(cells)} |")

    return "\n".join(lines)


def table_temperature_sensitivity(rows: list[dict]) -> str:
    """Table 10: Temperature sensitivity — pass rate delta between T=0.0 and T=1.0."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[model_key(r)].append(r)

    lines = [
        "## Table 10: Temperature Sensitivity (Pass Rate at T=0.0 vs T=1.0)",
        "",
        "| Model | T=0.0 Pass % | T=1.0 Pass % | Delta | Direction |",
        "|:------|-------------:|-------------:|------:|:----------|",
    ]

    for mk in sorted(by_model):
        t0_rows = [r for r in by_model[mk] if r.get("temperature", "") in ("0.0", "0")
                    and r.get("result") in ("PASS", "PARTIAL", "FAIL")]
        t1_rows = [r for r in by_model[mk] if r.get("temperature", "") in ("1.0", "1")
                    and r.get("result") in ("PASS", "PARTIAL", "FAIL")]

        if not t0_rows or not t1_rows:
            lines.append(f"| {mk} | - | - | - | - |")
            continue

        p0 = sum(1 for r in t0_rows if r["result"] == "PASS")
        p1 = sum(1 for r in t1_rows if r["result"] == "PASS")
        pct0 = round(p0 / len(t0_rows) * 100, 1)
        pct1 = round(p1 / len(t1_rows) * 100, 1)
        delta = round(pct1 - pct0, 1)
        direction = "improved" if delta > 0 else "degraded" if delta < 0 else "unchanged"
        lines.append(f"| {mk} | {pct0}% | {pct1}% | {delta:+.1f}pp | {direction} |")

    return "\n".join(lines)


def table_fishers_exact(rows: list[dict]) -> str:
    """Table 11: Fisher's exact test — pairwise model comparison of pass rates.

    Tests whether each pair of models has significantly different pass rates.
    Reports only pairs with p < 0.05 (Bonferroni-corrected).
    """
    try:
        from scipy.stats import fisher_exact
    except ImportError:
        return ("## Table 11: Pairwise Model Comparison (Fisher's Exact Test)\n\n"
                "*scipy not available — run with `uv run --with scipy python analyze_results.py` "
                "to enable this table (also yields exact Beta credible intervals).*")

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("result") in ("PASS", "PARTIAL", "FAIL"):
            by_model[model_key(r)].append(r)

    models = sorted(by_model)
    n_pairs = len(models) * (len(models) - 1) // 2
    alpha_corrected = 0.05 / n_pairs if n_pairs > 0 else 0.05

    lines = [
        "## Table 11: Pairwise Model Comparison (Fisher's Exact Test)",
        "",
        f"Bonferroni-corrected significance threshold: p < {alpha_corrected:.6f} "
        f"({n_pairs} pairs).",
        "",
        "| Model A | Model B | Pass A | n A | Pass B | n B | p-value | Significant |",
        "|:--------|:--------|-------:|----:|-------:|----:|--------:|:------------|",
    ]

    for i, mk_a in enumerate(models):
        for mk_b in models[i + 1:]:
            rows_a = by_model[mk_a]
            rows_b = by_model[mk_b]
            pass_a = sum(1 for r in rows_a if r["result"] == "PASS")
            fail_a = len(rows_a) - pass_a
            pass_b = sum(1 for r in rows_b if r["result"] == "PASS")
            fail_b = len(rows_b) - pass_b

            table = [[pass_a, fail_a], [pass_b, fail_b]]
            _, p_val = fisher_exact(table)

            sig = "Yes" if p_val < alpha_corrected else ""
            lines.append(
                f"| {mk_a} | {mk_b} | {pass_a} | {len(rows_a)} "
                f"| {pass_b} | {len(rows_b)} | {p_val:.6f} | {sig} |"
            )

    return "\n".join(lines)


def table_parameter_correctness(rows: list[dict]) -> str:
    """Table 6: Parameter correctness rates by model."""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("parameters_correct") in ("CORRECT", "PARTIAL", "INCORRECT"):
            by_model[model_key(r)].append(r)

    if not by_model:
        return "## Table 6: Parameter Correctness\n\nNo parameter correctness data."

    lines = [
        "## Table 6: Parameter Correctness by Model",
        "",
        "| Model | n | CORRECT | PARTIAL | INCORRECT | Correct % |",
        "|:------|--:|--------:|--------:|----------:|----------:|",
    ]

    for mk in sorted(by_model):
        model_rows = by_model[mk]
        n = len(model_rows)
        c = sum(1 for r in model_rows if r["parameters_correct"] == "CORRECT")
        p = sum(1 for r in model_rows if r["parameters_correct"] == "PARTIAL")
        i = sum(1 for r in model_rows if r["parameters_correct"] == "INCORRECT")
        pct = round(c / n * 100, 1) if n else 0
        lines.append(f"| {mk} | {n} | {c} | {p} | {i} | {pct}% |")

    return "\n".join(lines)


def summary_statistics(rows: list[dict]) -> str:
    """Overall summary paragraph."""
    models = sorted(set(model_key(r) for r in rows))
    prompts = sorted(set(int(r["prompt_id"]) for r in rows))
    scored = [r for r in rows if r.get("result") in ("PASS", "PARTIAL", "FAIL")]
    unscored = len(rows) - len(scored)

    reviewed = sum(1 for r in rows if r.get("reviewed", "").strip() == "true")

    lines = [
        "## Summary",
        "",
        f"- **Models evaluated:** {len(models)}",
        f"- **Unique prompts:** {len(prompts)} (8 capability categories)",
        f"- **Total evaluations:** {len(rows)}",
        f"- **Scored:** {len(scored)} ({len(rows) - unscored}/{len(rows)})",
        f"- **Unscored:** {unscored}",
        f"- **Human-reviewed:** {reviewed}",
    ]

    if scored:
        total_p, _, pct = pass_rate(scored)
        pp_pct = partial_rate(scored)
        lo, hi = beta_binomial_ci(
            sum(1 for r in scored if r["result"] == "PASS"),
            len(scored),
        )
        lines.extend([
            f"- **Overall pass rate:** {pct}% [{lo:.1%}, {hi:.1%}]",
            f"- **Overall pass+partial rate:** {pp_pct}%",
            f"- **Mean latency:** {avg_latency(rows)}s",
            f"- **Median latency:** {median_latency(rows)}s",
        ])

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze routing evaluation results and produce JAMIA-ready tables.",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Write report to file (default: stdout)",
    )
    parser.add_argument(
        "--results-dir", default=str(RESULTS_DIR),
        help=f"Directory containing result CSVs (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--include-unreviewed", action="store_true",
        help="Include rows with provisional scores that haven't been reviewed (default: block)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    print(f"Loading results from: {results_dir}")
    rows = load_all_results(results_dir)

    if not rows:
        print("No data to analyze.")
        sys.exit(1)

    # Hard gate: block analysis if unreviewed provisional rows exist
    unreviewed = [
        r for r in rows
        if r.get("provisional_result", "").strip()
        and r.get("reviewed", "").strip() != "true"
    ]
    if unreviewed and not args.include_unreviewed:
        by_prompt = defaultdict(int)
        for r in unreviewed:
            by_prompt[r.get("prompt_id", "?")] += 1
        print(f"\nERROR: {len(unreviewed)} rows have provisional scores pending human review.")
        print(f"  Prompts affected: {', '.join(f'P{p}({n})' for p, n in sorted(by_prompt.items()))}")
        print(f"\nOptions:")
        print(f"  1. Run `uv run python review_flagged.py` to complete review")
        print(f"  2. Re-run with --include-unreviewed to proceed anyway (not recommended)")
        sys.exit(1)
    elif unreviewed:
        print(f"\nWARNING: {len(unreviewed)} unreviewed provisional rows included (--include-unreviewed)")

    print(f"\nTotal rows loaded: {len(rows)}")

    # Partition: STUDY (four models) vs PRE-STUDY pilot (DeepSeek). All study
    # tables below are computed over study rows ONLY; the pilot is reported
    # separately and never folded into a study statistic.
    study_rows, prestudy_rows = split_study_prestudy(rows)
    print(f"Study rows: {len(study_rows)} ({len(set(model_key(r) for r in study_rows))} models); "
          f"pre-study rows: {len(prestudy_rows)} ({len(set(model_key(r) for r in prestudy_rows))} models)")
    print()

    # Build report — STUDY statistics use study_rows only
    sections = [
        "# Multi-Model Routing Evaluation Report",
        "",
        f"*{len(set(model_key(r) for r in study_rows))} study models, "
        f"{len(set(int(r['prompt_id']) for r in study_rows))} prompts, "
        f"8 capability categories (C1-C8). DeepSeek V3 (pre-study feasibility build) "
        f"is reported separately and excluded from all study statistics.*",
        "",
        summary_statistics(study_rows),
        "",
        table_pass_rate_by_model(study_rows),
        "",
        table_pass_rate_by_category(study_rows),
        "",
        table_model_comparison_matrix(study_rows),
        "",
        table_latency_by_model(study_rows),
        "",
        table_cross_server_chains(study_rows),
        "",
        table_parameter_correctness(study_rows),
        "",
        table_failure_modes(study_rows),
        "",
        table_open_vs_guided(study_rows),
        "",
        table_pass_rate_by_model_temperature(study_rows),
        "",
        table_pass_rate_by_category_temperature(study_rows),
        "",
        table_trajectory_diversity(study_rows),
        "",
        table_temperature_sensitivity(study_rows),
        "",
        table_fishers_exact(study_rows),
        "",
        table_category_contrasts(study_rows),
        "",
        prestudy_pilot_section(prestudy_rows),
    ]

    report = "\n".join(sections) + "\n"

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
