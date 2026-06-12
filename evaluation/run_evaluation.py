"""Multi-model routing evaluation harness for the OHDSI Agent.

Sends evaluation prompts to the webapp's /api/chat SSE endpoint,
parses tool_call / text / done / error / session events, and writes
results to a per-model CSV. Scoring columns are filled by score_results.py.

Two-condition design:
    open    — all 20 tools available (Select_Query + Get_Information_Schema)
    guided  — 18 tools (no raw SQL; forces build_cohort_definition path)

Evaluation matrix (primary — 6 models × 10 runs):
    Frontier : claude-sonnet-4-20250514, gpt-4o
    Mid      : claude-haiku-4-5-20251001, gpt-4o-mini
    Small    : qwen3:8b (ollama), llama3.1:8b (ollama)
    Temps    : 0.0, 0.3, 0.7, 1.0
    Runs     : 10 per model/temp/condition
    Open     : 33 prompts × 4 temps × 10 runs = 1,320 per model
    Guided   : 5 prompts × 4 temps × 10 runs  = 200 per model
    Total    : 9,120 evaluations

Satellite (qwen3:14b — 3 runs):
    Same temps and prompts, 3 runs per cell = 456 evaluations

Grand total: 9,576 evaluations

Usage:
    # Smoke test: one clinical prompt
    uv run python run_evaluation.py --provider ollama --model qwen3:8b --prompts 17

    # Full run: all 33 prompts, open condition, 10 runs, resumable
    uv run python run_evaluation.py --provider ollama --model qwen3:8b \
        --temperature 0.0 --condition open --runs 10 --resume

    # Guided condition (auto-selects the 5 cohort-relevant prompts)
    uv run python run_evaluation.py --provider ollama --model qwen3:8b \
        --temperature 0.0 --condition guided --runs 10 --resume

    # Claude API model
    uv run python run_evaluation.py --provider claude --model claude-sonnet-4-20250514 \
        --temperature 0.0 --condition open --runs 10 --resume

    # Full matrix: use run_full_matrix.sh
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── Graceful shutdown ─────────────────────────────────────────────────────

_shutdown_requested = False


def _handle_sigint(signum, frame):
    """Set shutdown flag on first Ctrl+C; force-exit on second."""
    global _shutdown_requested
    if _shutdown_requested:
        print("\n  Second interrupt — exiting immediately.")
        sys.exit(1)
    _shutdown_requested = True
    print("\n  Ctrl+C received — will stop after current prompt finishes.")


signal.signal(signal.SIGINT, _handle_sigint)

import httpx

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
PASSKEY = "changeme"
PROMPTS_CSV = Path(__file__).parent / "routing_test_results.csv"
RESULTS_DIR = Path(__file__).parent / "results"
TIMEOUT_SEC = 300

# Retry configuration for transient errors (rate limits, server errors)
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 10  # seconds; doubles each attempt: 10, 20, 40, 80, 160
RETRYABLE_ERROR_CODES = frozenset({
    "http_429",  # rate limit (OpenAI, Anthropic)
    "http_500",  # internal server error
    "http_502",  # bad gateway
    "http_503",  # service unavailable
    "http_529",  # overloaded (Anthropic)
    "timeout",   # request timeout
})

# Patterns that indicate a retryable error when found inside SSE error messages
# (the agent loop forwards full SDK error strings, not normalized codes)
RETRYABLE_ERROR_PATTERNS = (
    "overloaded",
    "rate_limit",
    "rate limit",
    "429",
    "529",
    "502",
    "503",
    "timeout",
    "connection reset",
    "connection closed",
    "incomplete chunked read",
)

# Patterns that indicate a fatal infrastructure failure — stop the run
# immediately. These are NOT retryable; continuing would produce results
# without observability data.
FATAL_ERROR_PATTERNS = (
    "langfuse:",    # Langfuse tracing pipeline down
)

# Prompts run under the "guided" condition (cohort-relevant, where the model
# could use either Select_Query or build_cohort_definition).
GUIDED_PROMPT_IDS = frozenset({19, 21, 31, 32, 33})

# ── Creator mapping ───────────────────────────────────────────────────────

# provider → creator (for API providers the mapping is 1:1)
_PROVIDER_CREATOR = {
    "claude": "anthropic",
    "openai": "openai",
    "gemini": "google",
    "deepseek": "deepseek",
}

# ollama model-prefix → creator
_OLLAMA_PREFIX_CREATOR = {
    "qwen": "qwen",
    "medgemma": "google",
    "gemma": "google",
    "llama": "meta",
    "mistral": "mistral",
    "phi": "microsoft",
    "granite": "ibm",
    "codellama": "meta",
    "deepseek": "deepseek",
    "command": "cohere",
    "starcoder": "bigcode",
}


def infer_creator(provider: str, model: str) -> str:
    """Derive the LLM creator from provider + model name."""
    if provider != "ollama":
        return _PROVIDER_CREATOR.get(provider, provider)
    # Ollama: match longest prefix first
    model_lower = model.split(":")[0].lower()
    for prefix in sorted(_OLLAMA_PREFIX_CREATOR, key=len, reverse=True):
        if model_lower.startswith(prefix):
            return _OLLAMA_PREFIX_CREATOR[prefix]
    return model_lower  # fallback: use the model family name itself


def sanitize_model_dir(model: str) -> str:
    """Turn 'qwen3:8b-16k' into 'qwen3_8b_16k'."""
    return model.replace(":", "_").replace("-", "_").replace("/", "_")


def get_git_commit() -> str:
    """Return the short SHA of HEAD, or 'unknown' if not in a git repo."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# ── Provenance tracking ──────────────────────────────────────────────────

PROVENANCE_COLUMNS = [
    "result_file",
    "condition",
    "creator",
    "provider",
    "model",
    "temperature",
    "run_number",
    "prompts_completed",
    "prompts_total",
    "harness_commit",
    "timestamp",
]
PROVENANCE_PATH = RESULTS_DIR / "result_provenance.csv"


def append_provenance(
    result_file: Path,
    condition: str,
    creator: str,
    provider: str,
    model: str,
    temperature: float | None,
    run_number: int,
    completed: int,
    total: int,
    commit: str,
) -> None:
    """Append a row to the central result_provenance.csv."""
    write_header = not PROVENANCE_PATH.exists() or PROVENANCE_PATH.stat().st_size == 0
    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROVENANCE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "result_file": str(result_file.relative_to(RESULTS_DIR)),
            "condition": condition,
            "creator": creator,
            "provider": provider,
            "model": model,
            "temperature": temperature if temperature is not None else "",
            "run_number": run_number,
            "prompts_completed": completed,
            "prompts_total": total,
            "harness_commit": commit,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Prompt:
    """A single evaluation prompt loaded from the CSV."""
    prompt_id: int
    category_code: str
    category_name: str
    text: str
    expected_tools: str


@dataclass
class RunResult:
    """Captured result from a single prompt execution."""
    tools_called: list[str] = field(default_factory=list)
    tool_arguments: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)  # {"name": str, "result": str}
    text_response: str = ""
    errors: list[str] = field(default_factory=list)
    rounds: int = 0
    session_id: str = ""
    latency_sec: float = 0.0


# ── Prompt loading ─────────────────────────────────────────────────────────

def load_prompts(csv_path: Path, subset: list[int] | None = None) -> list[Prompt]:
    """Load evaluation prompts from the routing_test_results.csv."""
    prompts = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = int(row["prompt_id"])
            if subset and pid not in subset:
                continue
            prompts.append(Prompt(
                prompt_id=pid,
                category_code=row["category_code"],
                category_name=row["category_name"],
                text=row["prompt"],
                expected_tools=row["expected_tools"],
            ))
    return prompts


# ── Resumability ──────────────────────────────────────────────────────────

def scan_existing_runs(output_dir: Path, expected_prompt_count: int) -> tuple[int, set[int]]:
    """Scan existing CSV files to determine completed runs and partial progress.

    Only counts a prompt as done if it completed without errors.
    Failed prompts (non-empty errors column) are excluded so they
    get retried on --resume.

    Returns:
        (complete_run_count, partial_prompt_ids)
        - complete_run_count: number of fully-complete run CSVs
        - partial_prompt_ids: prompt_ids successfully completed in the latest
          incomplete run (empty set if no partial run exists)
    """
    if not output_dir.exists():
        return 0, set()

    csvs = sorted(output_dir.glob("*.csv"))
    if not csvs:
        return 0, set()

    complete = 0
    partial_ids: set[int] = set()
    partial_file: Path | None = None

    for csv_path in csvs:
        ids = set()
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    err = row.get("errors", "").strip()
                    # Count prompts that completed without errors, OR that
                    # hit the max-rounds limit (a valid result, not retryable).
                    if not err or err == "Maximum tool rounds reached":
                        ids.add(int(row["prompt_id"]))
        except (KeyError, ValueError, csv.Error):
            continue

        if len(ids) >= expected_prompt_count:
            complete += 1
        else:
            # Keep track of the latest partial run
            partial_ids = ids
            partial_file = csv_path

    return complete, partial_ids


# ── SSE parsing ────────────────────────────────────────────────────────────

def parse_sse_lines(raw: str) -> list[tuple[str, str]]:
    """Parse raw SSE text into (event_type, data_json) pairs.

    Wire format from agent.py SSEEvent.encode():
        event: <type>\\ndata: <json>\\n\\n
    """
    events = []
    current_event = ""
    current_data = ""

    for line in raw.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            current_data = line[6:]
        elif line == "":
            if current_event and current_data:
                events.append((current_event, current_data))
            current_event = ""
            current_data = ""

    # Catch trailing event without final blank line
    if current_event and current_data:
        events.append((current_event, current_data))

    return events


# ── Auth ───────────────────────────────────────────────────────────────────

async def get_auth_token(client: httpx.AsyncClient, base_url: str) -> str:
    """Login and return a JWT bearer token."""
    resp = await client.post(
        f"{base_url}/api/auth/login",
        json={"passkey": PASSKEY},
    )
    resp.raise_for_status()
    return resp.json()["token"]


# ── Single prompt execution ────────────────────────────────────────────────

async def run_prompt(
    client: httpx.AsyncClient,
    token: str,
    prompt: Prompt,
    provider: str,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    temperature: float | None = None,
    allow_raw_sql: bool = True,
) -> RunResult:
    """Send one prompt to /api/chat and parse the SSE stream."""
    result = RunResult()
    t0 = time.monotonic()

    try:
        # Stream the SSE response
        payload = {
            "message": prompt.text,
            "provider": provider,
            "model": model,
            "allow_raw_sql": allow_raw_sql,
            # No session_id → fresh session per prompt
        }
        if temperature is not None:
            payload["temperature"] = temperature
        async with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SEC,
        ) as resp:
            resp.raise_for_status()

            # Accumulate raw SSE text
            raw_chunks: list[str] = []
            async for chunk in resp.aiter_text():
                raw_chunks.append(chunk)

    except httpx.TimeoutException:
        result.errors.append("timeout")
        result.latency_sec = round(time.monotonic() - t0, 2)
        return result
    except httpx.HTTPStatusError as e:
        result.errors.append(f"http_{e.response.status_code}")
        result.latency_sec = round(time.monotonic() - t0, 2)
        return result
    except Exception as e:
        result.errors.append(str(e)[:200])
        result.latency_sec = round(time.monotonic() - t0, 2)
        return result

    result.latency_sec = round(time.monotonic() - t0, 2)

    # Parse SSE events
    raw = "".join(raw_chunks)
    events = parse_sse_lines(raw)

    text_parts: list[str] = []
    for event_type, data_json in events:
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError:
            continue

        if event_type == "tool_call":
            result.tools_called.append(data.get("name", ""))
            result.tool_arguments.append(data.get("arguments", {}))

        elif event_type == "tool_result":
            result.tool_results.append({
                "name": data.get("name", ""),
                "result": str(data.get("result", ""))[:2000],
            })

        elif event_type == "text":
            text = data.get("text", "")
            if text:
                text_parts.append(text)

        elif event_type == "done":
            result.rounds = data.get("rounds", 0)

        elif event_type == "error":
            result.errors.append(data.get("error", "unknown"))

        elif event_type == "session":
            result.session_id = data.get("session_id", "")

    result.text_response = "\n".join(text_parts)

    return result


# ── CSV output ─────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "prompt_id",
    "category_code",
    "category_name",
    "prompt",
    "expected_tools",
    "condition",
    "provider",
    "model",
    "temperature",
    "run_number",
    "result",               # scored by score_results.py: PASS / PARTIAL / FAIL
    "tools_called",
    "tool_arguments",
    "parameters_correct",   # scored by score_results.py: CORRECT / PARTIAL / INCORRECT / N/A
    "latency_sec",
    "rounds",
    "text_response",
    "errors",
    "session_id",
    "notes",
    "timestamp",
]


def _compact_tool_arguments(tool_arguments: list[dict]) -> str:
    """Serialize tool_arguments to compact JSON, replacing large blobs."""
    compacted = []
    for args in tool_arguments:
        out = dict(args)
        if "spec_json" in out:
            out["spec_json"] = True  # scoring only checks existence
        compacted.append(out)
    return json.dumps(compacted, separators=(",", ":"))


def make_row(
    prompt: Prompt,
    run: RunResult,
    condition: str,
    provider: str,
    model: str,
    temperature: float | None = None,
    run_number: int = 1,
) -> dict:
    """Build a single CSV row dict from a prompt and its run result."""
    return {
        "prompt_id": prompt.prompt_id,
        "category_code": prompt.category_code,
        "category_name": prompt.category_name,
        "prompt": prompt.text,
        "expected_tools": prompt.expected_tools,
        "condition": condition,
        "provider": provider,
        "model": model,
        "temperature": temperature if temperature is not None else "",
        "run_number": run_number,
        "result": "",               # filled by score_results.py
        "tools_called": "|".join(run.tools_called),
        "tool_arguments": _compact_tool_arguments(run.tool_arguments),
        "parameters_correct": "",   # filled by score_results.py
        "latency_sec": run.latency_sec,
        "rounds": run.rounds,
        "text_response": run.text_response[:500].replace("\n", " \\n "),
        "errors": "|".join(run.errors),
        "session_id": run.session_id,
        "notes": "",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _is_retryable(errors: list[str]) -> bool:
    """Check whether any error in the list is retryable.

    Matches both normalized codes (e.g. "http_529", "timeout") and
    full SDK error messages forwarded through SSE (e.g. "Error code: 529 - ...").
    """
    for e in errors:
        if e in RETRYABLE_ERROR_CODES:
            return True
        e_lower = e.lower()
        if any(pat in e_lower for pat in RETRYABLE_ERROR_PATTERNS):
            return True
    return False


def _is_fatal(errors: list[str]) -> bool:
    """Check whether any error indicates a fatal infrastructure failure.

    Fatal errors stop the run immediately — continuing would produce
    results without required observability data (e.g. Langfuse traces).
    """
    for e in errors:
        e_lower = e.lower()
        if any(pat in e_lower for pat in FATAL_ERROR_PATTERNS):
            return True
    return False


# ── Single run execution ──────────────────────────────────────────────────

async def execute_run(
    prompts: list[Prompt],
    skip_ids: set[int],
    output_path: Path,
    append: bool,
    condition: str,
    provider: str,
    model: str,
    temperature: float | None,
    run_number: int,
    delay: float,
    base_url: str,
) -> int:
    """Execute one evaluation run, writing results to output_path.

    Returns the number of prompts completed in this invocation.
    """
    global _shutdown_requested
    allow_raw_sql = (condition == "open")
    mode = "a" if append else "w"
    completed = 0

    csv_file = open(output_path, mode, newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
    if not append:
        writer.writeheader()
    csv_file.flush()

    try:
        async with httpx.AsyncClient() as client:
            print("  Authenticating...", end=" ")
            token = await get_auth_token(client, base_url)
            print("OK")

            remaining = [p for p in prompts if p.prompt_id not in skip_ids]
            total_remaining = len(remaining)

            for i, prompt in enumerate(remaining):
                print(
                    f"  [{i + 1}/{total_remaining}] "
                    f"P{prompt.prompt_id:02d} ({prompt.category_code}: {prompt.category_name})"
                )
                print(f"    → {prompt.text[:80]}...")

                for attempt in range(1, MAX_RETRIES + 1):
                    run = await run_prompt(
                        client, token, prompt, provider, model, base_url,
                        temperature=temperature, allow_raw_sql=allow_raw_sql,
                    )
                    if run.errors and attempt < MAX_RETRIES:
                        retryable = _is_retryable(run.errors)
                        if retryable:
                            backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                            print(
                                f"    Retry {attempt}/{MAX_RETRIES}: {run.errors}. "
                                f"Waiting {backoff}s..."
                            )
                            await asyncio.sleep(backoff)
                            continue
                    break

                # Check for fatal infrastructure errors BEFORE writing results.
                # Fatal errors (e.g. Langfuse down) mean the data pipeline is
                # broken — write the errored row for diagnostics, then stop.
                fatal = _is_fatal(run.errors) if run.errors else False

                writer.writerow(make_row(
                    prompt, run, condition, provider, model,
                    temperature=temperature, run_number=run_number,
                ))
                csv_file.flush()
                completed += 1

                tools_str = " → ".join(run.tools_called) if run.tools_called else "(none)"
                print(f"    Tools: {tools_str}")
                print(f"    Rounds: {run.rounds} | Latency: {run.latency_sec}s")
                if run.errors:
                    print(f"    Errors: {', '.join(run.errors)}")

                if fatal:
                    print(
                        f"\n  *** FATAL: Infrastructure error detected — stopping run."
                        f"\n  Last good prompt: P{prompt.prompt_id:02d} will be retried on --resume."
                        f"\n  {completed} prompts saved. Use --resume to continue after fixing."
                    )
                    # Set shutdown flag so outer loop also stops between runs
                    _shutdown_requested = True
                    break

                if _shutdown_requested:
                    print(f"\n  Stopping: {completed} prompts saved. Use --resume to continue.")
                    break

                if i < total_remaining - 1:
                    await asyncio.sleep(delay)

    finally:
        csv_file.close()

    return completed


# ── Main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run routing evaluation prompts against the OHDSI Agent webapp.",
    )
    parser.add_argument(
        "--provider", required=True,
        choices=["ollama", "claude", "openai", "gemini", "deepseek"],
        help="LLM provider",
    )
    parser.add_argument(
        "--model", required=True,
        help="Model name (e.g., qwen3:8b, claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--condition", default="open", choices=["open", "guided"],
        help="Tool condition: open (all 20 tools) or guided (no Select_Query). Default: open.",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of evaluation runs to perform (default: 1)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip completed runs and resume partial runs",
    )
    parser.add_argument(
        "--prompts", default=None,
        help="Comma-separated prompt IDs to run (e.g., 17,18,22,23). Default: all (or guided subset).",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds to wait between prompts (default: 2)",
    )
    parser.add_argument(
        "--creator", default=None,
        help="LLM creator name for output dir (e.g., qwen, anthropic). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--temperature", type=float, default=None,
        help="Sampling temperature (e.g., 0.0, 0.3, 0.7, 1.0). Default: provider default.",
    )
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"Webapp base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()

    base_url = args.base_url
    creator = args.creator or infer_creator(args.provider, args.model)
    condition = args.condition

    # Parse prompt subset
    subset = None
    if args.prompts:
        subset = [int(p.strip()) for p in args.prompts.split(",")]
    elif condition == "guided":
        # Auto-select the 5 cohort-relevant prompts for guided condition
        subset = sorted(GUIDED_PROMPT_IDS)

    # Load prompts
    prompts = load_prompts(PROMPTS_CSV, subset)
    if not prompts:
        print("No prompts matched. Check --prompts IDs (1-33).")
        sys.exit(1)

    harness_commit = get_git_commit()
    temp_str = f"{args.temperature}" if args.temperature is not None else "default"
    temp_dir = f"temp_{args.temperature}" if args.temperature is not None else "temp_default"
    model_dir = sanitize_model_dir(args.model)

    # Output hierarchy: results/<creator>/<model>/temp_<t>/<condition>/
    output_dir = RESULTS_DIR / creator / model_dir / temp_dir / condition

    print(f"Evaluation: {args.provider}/{args.model} (creator: {creator})")
    print(f"Condition: {condition} ({'all tools' if condition == 'open' else 'no Select_Query'})")
    print(f"Temperature: {temp_str}")
    print(f"Harness commit: {harness_commit}")
    print(f"Prompts: {len(prompts)} ({', '.join(str(p.prompt_id) for p in prompts)})")
    print(f"Target runs: {args.runs}")
    print(f"Resume: {args.resume}")
    print(f"Output dir: {output_dir}")
    print(f"Delay: {args.delay}s between prompts")
    print()

    # ── Resumability check ─────────────────────────────────────────────
    completed_runs = 0
    partial_ids: set[int] = set()

    if args.resume:
        completed_runs, partial_ids = scan_existing_runs(output_dir, len(prompts))
        if completed_runs >= args.runs:
            print(f"Already have {completed_runs}/{args.runs} complete runs. Nothing to do.")
            return
        if partial_ids:
            print(f"Found {completed_runs} complete runs + 1 partial ({len(partial_ids)}/{len(prompts)} prompts)")
        else:
            print(f"Found {completed_runs} complete runs")
        print()

    # ── Execute runs ────────────────────────────────────────────────────
    start_run = completed_runs + 1
    # If there's a partial run, the first iteration resumes it
    has_partial = bool(partial_ids)

    for run_num in range(start_run, args.runs + 1):
        is_resuming_partial = (run_num == start_run and has_partial)

        if is_resuming_partial:
            # Find the partial CSV to append to
            csvs = sorted(output_dir.glob("*.csv"))
            # The partial file is the last one that isn't complete
            output_path = csvs[-1] if csvs else None
            if output_path is None:
                is_resuming_partial = False
                partial_ids = set()

        if not is_resuming_partial:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_path = output_dir / f"{ts}.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            partial_ids = set()

        skip_ids = partial_ids if is_resuming_partial else set()
        skip_label = f" (resuming, skipping {len(skip_ids)} done)" if skip_ids else ""

        print(f"{'='*60}")
        print(f"Run {run_num}/{args.runs}{skip_label}")
        print(f"Output: {output_path}")
        print(f"{'='*60}")

        completed = await execute_run(
            prompts=prompts,
            skip_ids=skip_ids,
            output_path=output_path,
            append=is_resuming_partial,
            condition=condition,
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            run_number=run_num,
            delay=args.delay,
            base_url=base_url,
        )

        total_in_file = completed + len(skip_ids)

        append_provenance(
            result_file=output_path,
            condition=condition,
            creator=creator,
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            run_number=run_num,
            completed=total_in_file,
            total=len(prompts),
            commit=harness_commit,
        )

        print()
        print(f"  Run {run_num} complete: {total_in_file}/{len(prompts)} prompts")
        print(f"  Written to: {output_path}")
        print()

        if _shutdown_requested:
            print(f"Shutdown requested. {run_num - start_run + 1} run(s) saved. Use --resume to continue.")
            break

        # Brief cooldown between runs
        if run_num < args.runs:
            print("  Cooldown 5s before next run...")
            await asyncio.sleep(5)
    else:
        print(f"All runs complete. Provenance logged to: {PROVENANCE_PATH}")
        print(f"Run score_results.py to auto-fill result + parameters_correct")


if __name__ == "__main__":
    asyncio.run(main())
