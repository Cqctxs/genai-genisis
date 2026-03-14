import asyncio
import json
import re

import structlog
from pydantic_ai import Agent

from agent.schemas import AnalysisResult, Hotspot, OptimizationChange, OptimizationPlan
from agent.state import AgentState
from services.gemini_service import (
    GEMINI_PRO,
    PRO_SETTINGS,
    run_agent_logged,
)
from services.github_service import read_file

log = structlog.get_logger()

MIN_SIZE_RATIO = 0.25
DESTRUCTIVE_PATTERNS = [
    re.compile(r"^\s*(return\s+(null|undefined|None|void|0|''|\"\"|false|\[\]|\{\})\s*;?\s*)$", re.MULTILINE),
    re.compile(r"^\s*(pass\s*)$", re.MULTILINE),
]


def _is_destructive_change(change: OptimizationChange) -> bool:
    """Detect when an 'optimization' guts or trivializes a function.

    Returns True if the optimized snippet is suspiciously shorter than the
    original, or consists entirely of no-op / trivial return statements.
    """
    orig = change.original_snippet.strip()
    opt = change.optimized_snippet.strip()

    if not opt:
        return True

    if len(orig) > 20 and len(opt) / len(orig) < MIN_SIZE_RATIO:
        log.warning(
            "optimization_suspiciously_short",
            function=change.function_name,
            file=change.file,
            original_len=len(orig),
            optimized_len=len(opt),
            ratio=round(len(opt) / len(orig), 2),
        )
        return True

    opt_lines = [line.strip() for line in opt.splitlines() if line.strip()]
    if len(opt_lines) <= 2:
        for pattern in DESTRUCTIVE_PATTERNS:
            if all(pattern.match(line) for line in opt_lines):
                log.warning(
                    "optimization_trivial_noop",
                    function=change.function_name,
                    file=change.file,
                    optimized_snippet=opt[:200],
                )
                return True

    return False

OPTIMIZER_PROMPT = """You are an elite performance optimization engineer. Your goal is to improve performance while ensuring absolute functional parity. Given:
1. A performance bottleneck with severity and reasoning
2. Benchmark results showing actual timing/memory data
3. The source code of the affected file

Generate optimized versions of the bottleneck code. For each change:
- Show the exact original code snippet
- Show the optimized replacement
- Explain what was changed and why
- Estimate the expected improvement

CRITICAL REQUIREMENTS:
- The optimized functionality MUST MATCH EXACTLY the original functionality. Ensure edge cases, return types, and exceptions remain identical.
- Adapt your optimization strategy based on the program's context:
  - For single-input / compute-bound programs: Focus purely on algorithmic efficiency, memory allocation, reducing unnecessary operations, and data structures. Do not attempt I/O concurrency or batching optimizations where they do not naturally apply.
  - For I/O bound programs (DB, network): Focus on async/concurrent I/O, connection pooling, and batching.
  - For large datasets or iteration: Use generators, lazy evaluation, stream processing, or vectorized operations (e.g. NumPy if available) to minimize memory footprint and execution time.
  - For repeated heavy calls/computations: Add caching/memoization appropriately.

Standard Optimization strategies to consider when applicable:
- Algorithm improvements (e.g., O(n^2) -> O(n log n) -> O(1))
- Reducing memory allocations in hot loops (in-place operations, avoiding unnecessary copies/list comprehensions)
- Using more efficient data structures (e.g., sets for lookups, deque for queues, tuples instead of lists)
- Async/concurrent I/O instead of blocking calls (ONLY if multi-input or actually I/O bound)

Be extremely precise: only modify code that actually impacts performance, and PRESERVE STRICT CORRECTNESS."""

BIAS_INSTRUCTIONS: dict[str, str] = {
    "speed": (
        "CRITICAL PRIORITY: Maximize execution speed above all else. "
        "It is acceptable to use more memory (caching, memoization, precomputation, "
        "lookup tables) if it results in faster execution. Prefer O(1) lookups over "
        "O(n) scans, even at the cost of higher memory footprint."
    ),
    "memory": (
        "CRITICAL PRIORITY: Minimize memory usage above all else. "
        "Prefer streaming/iterative approaches over buffering, generators over lists, "
        "in-place mutations over copies, and compact data structures. Accept slightly "
        "slower execution if it meaningfully reduces peak memory."
    ),
    "balanced": (
        "PRIORITY: Balance execution speed and memory usage. "
        "Optimize for the best overall efficiency without heavily sacrificing one metric for the other."
    ),
}


def _build_regression_section(
    file_path: str,
    initial_results: list[dict],
    previous_results: list[dict],
) -> str:
    """Build a prompt section describing performance regressions from a prior attempt.

    Compares initial (baseline) results against the most recent post-optimization
    results for functions in this file. Only emits warnings for functions that
    got slower or used more memory.
    """
    initial_by_fn: dict[str, dict] = {}
    for r in initial_results:
        if r.get("file") == file_path and r.get("function_name"):
            initial_by_fn[r["function_name"]] = r

    regressions: list[str] = []
    for r in previous_results:
        if r.get("file") != file_path:
            continue
        fn = r.get("function_name", "")
        baseline = initial_by_fn.get(fn)
        if not baseline:
            continue

        old_time = baseline.get("avg_time_ms", 0)
        new_time = r.get("avg_time_ms", 0)
        old_mem = baseline.get("memory_peak_mb", 0)
        new_mem = r.get("memory_peak_mb", 0)

        parts: list[str] = []
        if old_time > 0 and new_time >= old_time:
            pct = ((new_time - old_time) / old_time) * 100
            parts.append(f"time {old_time:.2f}ms -> {new_time:.2f}ms (+{pct:.1f}%)")
        if old_mem > 0 and new_mem > old_mem:
            pct = ((new_mem - old_mem) / old_mem) * 100
            parts.append(f"memory {old_mem:.2f}MB -> {new_mem:.2f}MB (+{pct:.1f}%)")

        if parts:
            regressions.append(f"- `{fn}`: {', '.join(parts)}")

    if not regressions:
        return ""

    return f"""
## PERFORMANCE REGRESSION (CRITICAL — previous attempt made things WORSE)

Your previous optimization attempt caused regressions on the following function(s):

{chr(10).join(regressions)}

You MUST use a COMPLETELY DIFFERENT optimization strategy this time.
Do NOT repeat the same approach. Consider alternative techniques:
- If you tried algorithmic changes, try caching/memoization instead
- If you tried caching, try algorithmic restructuring instead
- If you tried batching, try lazy evaluation or streaming instead
- If you inlined code, try reducing allocations or using more efficient data structures

The goal is to make every function FASTER and LEANER than the original baseline,
not just different from your last attempt.
"""


def _create_optimizer_agent() -> Agent[None, OptimizationPlan]:
    """Create an optimizer agent using Gemini Pro with MEDIUM thinking."""
    agent = Agent(
        GEMINI_PRO,
        output_type=OptimizationPlan,
        system_prompt=OPTIMIZER_PROMPT,
    )

    agent._codemark_system_prompt = OPTIMIZER_PROMPT  # type: ignore[attr-defined]
    agent._codemark_output_type = "OptimizationPlan"  # type: ignore[attr-defined]
    agent._model_str = GEMINI_PRO  # type: ignore[attr-defined]

    return agent


async def _optimize_file(
    file_path: str,
    file_content: str,
    hotspots: list[Hotspot],
    benchmark_results: list[dict],
    correctness_failures: list[dict] | None = None,
    previous_results: list[dict] | None = None,
    bias_instruction: str = "",
) -> tuple[str, list[OptimizationChange], str]:
    """Optimize a single file's hotspots. Returns (file_path, changes, optimized_content).

    Uses a Thinking model with a sandbox tool so the agent can iteratively test
    its code before finalizing. Changes are then passed through the Reviewer
    agent (actor-critic pattern) and a destructive-change guard.
    """
    from agent.nodes.reviewer import review_optimization

    file_results = [r for r in benchmark_results if r.get("file") == file_path]

    agent = _create_optimizer_agent()

    hotspot_info = [
        {"function_name": h.function_name, "severity": h.severity,
         "category": h.category, "reasoning": h.reasoning}
        for h in hotspots
    ]

    correctness_section = ""
    if correctness_failures:
        file_failures = [f for f in correctness_failures if f.get("file") == file_path]
        if file_failures:
            correctness_section = f"""
## CORRECTNESS FAILURE (CRITICAL — must fix)

Your previous optimization broke the following function(s). The output fingerprint
changed, meaning the function now returns DIFFERENT results for the same input.
You MUST fix these while still optimizing for performance.

```json
{json.dumps(file_failures, indent=2)}
```

- `initial_fingerprint` = the correct output hash from the original code.
- `final_fingerprint` = the broken output hash from your previous optimization.

Rules:
- The optimized code MUST produce the EXACT same output as the original for any input.
- If you cannot optimize a function without changing its output, leave it unchanged.
- Focus on structural/algorithmic improvements that preserve semantics (memoization,
  caching, reducing allocations, batching) rather than logic changes.
"""

    regression_section = ""
    if previous_results:
        regression_section = _build_regression_section(
            file_path, benchmark_results, previous_results,
        )

    prompt = f"""## Bottlenecks in {file_path}
```json
{json.dumps(hotspot_info, indent=2)}
```

## Benchmark Results (Baseline)
```json
{json.dumps(file_results, indent=2)}
```
{correctness_section}{regression_section}
## Source File: {file_path}
```
{file_content[:8000]}
```

## Optimization Objective
{bias_instruction if bias_instruction else BIAS_INSTRUCTIONS["balanced"]}

Optimize the bottleneck functions in this file."""

    try:
        result = await run_agent_logged(
            agent,  # type: ignore[arg-type]
            prompt,
            node_name=f"optimize_{file_path.split('/')[-1]}",
            model_settings=PRO_SETTINGS,
        )
        plan: OptimizationPlan = result.output  # type: ignore[assignment]

        # Gate 1: Destructive change guard (fast, local)
        non_destructive: list[OptimizationChange] = []
        for change in plan.changes:
            if _is_destructive_change(change):
                log.warning(
                    "optimization_rejected_destructive",
                    file=change.file,
                    function=change.function_name,
                    explanation=change.explanation[:200],
                )
                continue
            non_destructive.append(change)

        # Gate 2: Reviewer agent critique (LLM-based, parallel with other files)
        reviews = await review_optimization(non_destructive, file_content, file_path)

        review_by_fn = {r.function_name: r for r in reviews}
        accepted_changes: list[OptimizationChange] = []
        for change in non_destructive:
            review = review_by_fn.get(change.function_name)
            if review and not review.approved:
                log.warning(
                    "optimization_rejected_by_reviewer",
                    file=change.file,
                    function=change.function_name,
                    reason=review.reason[:200],
                    suggestion=review.suggestion[:200],
                )
                continue
            accepted_changes.append(change)

        optimized = file_content
        for change in accepted_changes:
            optimized = optimized.replace(change.original_snippet, change.optimized_snippet)

        for change in accepted_changes:
            log.info(
                "optimization_change",
                file=change.file,
                function=change.function_name,
                explanation=change.explanation[:200],
                expected_improvement=change.expected_improvement,
            )

        total = len(plan.changes)
        if len(accepted_changes) < total:
            log.info(
                "optimization_changes_filtered",
                file=file_path,
                total=total,
                accepted=len(accepted_changes),
                rejected_destructive=total - len(non_destructive),
                rejected_by_reviewer=len(non_destructive) - len(accepted_changes),
            )

        return file_path, accepted_changes, optimized
    except Exception as e:
        log.error("optimize_file_failed", file=file_path, error=str(e))
        return file_path, [], file_content


async def optimize_node(state: AgentState) -> dict:
    """Generate optimized code for identified bottlenecks, parallelized per-file."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    initial_results = state.get("initial_results", [])
    final_results = state.get("final_results", [])
    repo_path = state.get("repo_path", "")
    correctness_failures = state.get("correctness_failures", [])
    optimization_bias = state.get("optimization_bias", "balanced")
    bias_instruction = BIAS_INSTRUCTIONS.get(optimization_bias, BIAS_INSTRUCTIONS["balanced"])

    file_hotspots: dict[str, list[Hotspot]] = {}
    for hotspot in analysis.hotspots:
        file_hotspots.setdefault(hotspot.file, []).append(hotspot)

    # When retrying due to correctness failures, only re-optimize the broken files
    if correctness_failures:
        broken_files = {f["file"] for f in correctness_failures}
        file_hotspots = {k: v for k, v in file_hotspots.items() if k in broken_files}
        log.info(
            "optimize_correctness_retry",
            broken_files=list(broken_files),
            hotspots_to_fix=sum(len(v) for v in file_hotspots.values()),
        )

    affected_files: dict[str, str] = {}
    for file_path in file_hotspots:
        try:
            affected_files[file_path] = read_file(repo_path, file_path)
        except Exception as e:
            log.warning("optimize_read_file_failed", file=file_path, error=str(e))

    is_retry = bool(final_results)
    log.info(
        "optimize_start",
        num_hotspots=sum(len(v) for v in file_hotspots.values()),
        num_files=len(affected_files),
        affected_files=list(affected_files.keys()),
        has_correctness_failures=bool(correctness_failures),
        is_retry=is_retry,
    )

    tasks = [
        _optimize_file(
            file_path, content, file_hotspots[file_path], initial_results,
            correctness_failures=correctness_failures,
            previous_results=final_results if is_retry else None,
            bias_instruction=bias_instruction,
        )
        for file_path, content in affected_files.items()
    ]
    results = await asyncio.gather(*tasks)

    # Merge: keep previous optimizations for files NOT being re-optimized
    optimized_files = dict(state.get("optimized_files", {}))
    total_changes = 0
    for file_path, changes, optimized_content in results:
        optimized_files[file_path] = optimized_content
        total_changes += len(changes)

    log.info(
        "optimize_complete",
        changes=total_changes,
        files_modified=len(optimized_files),
    )

    return {
        **state,
        "optimized_files": optimized_files,
        "messages": state.get("messages", []) + [
            f"Generated {total_changes} optimizations across {len(optimized_files)} files"
        ],
    }
