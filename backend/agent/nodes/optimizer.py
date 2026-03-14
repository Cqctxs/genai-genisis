import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkResult, Hotspot, OptimizationChange, OptimizationPlan
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged
from services.github_service import read_file

log = structlog.get_logger()

OPTIMIZER_PROMPT = """You are an elite performance optimization engineer. Given:
1. A performance bottleneck with severity and reasoning
2. Benchmark results showing actual timing/memory data
3. The source code of the affected file

Generate optimized versions of the bottleneck code. For each change:
- Show the exact original code snippet
- Show the optimized replacement
- Explain what was changed and why
- Estimate the expected improvement

Optimization strategies to consider:
- Algorithm improvements (e.g., O(n^2) -> O(n log n))
- Async/concurrent I/O instead of blocking calls
- Batch API calls instead of sequential ones
- Add caching for repeated computations
- Reduce memory allocations in hot loops
- Use more efficient data structures
- Connection pooling for database queries
- Lazy evaluation where appropriate

Be precise: only modify code that actually impacts performance. Preserve correctness."""

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


async def _optimize_file(
    file_path: str,
    file_content: str,
    hotspots: list[Hotspot],
    benchmark_results: list[dict],
    correctness_failures: list[dict] | None = None,
    bias_instruction: str = "",
) -> tuple[str, list[OptimizationChange], str]:
    """Optimize a single file's hotspots. Returns (file_path, changes, optimized_content).

    If correctness_failures is provided, the prompt focuses on fixing the broken
    functions while preserving the performance optimization intent.
    """
    file_results = [r for r in benchmark_results if r.get("file") == file_path]

    agent = get_agent(OptimizationPlan, OPTIMIZER_PROMPT, GEMINI_PRO)

    hotspot_info = [
        {"function_name": h.function_name, "severity": h.severity,
         "category": h.category, "reasoning": h.reasoning}
        for h in hotspots
    ]

    # Build correctness context if this file has failures from a previous attempt
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

    prompt = f"""## Bottlenecks in {file_path}
```json
{json.dumps(hotspot_info, indent=2)}
```

## Benchmark Results
```json
{json.dumps(file_results, indent=2)}
```
{correctness_section}
## Source File: {file_path}
```
{file_content[:8000]}
```

## Optimization Objective
{bias_instruction if bias_instruction else BIAS_INSTRUCTIONS["balanced"]}

Optimize the bottleneck functions in this file."""

    try:
        result = await run_agent_logged(agent, prompt, node_name=f"optimize_{file_path.split('/')[-1]}")
        plan: OptimizationPlan = result.output  # type: ignore[assignment]

        optimized = file_content
        for change in plan.changes:
            optimized = optimized.replace(change.original_snippet, change.optimized_snippet)

        for change in plan.changes:
            log.info(
                "optimization_change",
                file=change.file,
                function=change.function_name,
                explanation=change.explanation[:200],
                expected_improvement=change.expected_improvement,
            )

        return file_path, plan.changes, optimized
    except Exception as e:
        log.error("optimize_file_failed", file=file_path, error=str(e))
        return file_path, [], file_content


async def optimize_node(state: AgentState) -> dict:
    """Generate optimized code for identified bottlenecks, parallelized per-file."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    initial_results = state.get("initial_results", [])
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

    log.info(
        "optimize_start",
        num_hotspots=sum(len(v) for v in file_hotspots.values()),
        num_files=len(affected_files),
        affected_files=list(affected_files.keys()),
        has_correctness_failures=bool(correctness_failures),
    )

    tasks = [
        _optimize_file(
            file_path, content, file_hotspots[file_path], initial_results,
            correctness_failures=correctness_failures,
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
