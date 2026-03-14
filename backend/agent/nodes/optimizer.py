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


async def _optimize_file(
    file_path: str,
    file_content: str,
    hotspots: list[Hotspot],
    benchmark_results: list[dict],
) -> tuple[str, list[OptimizationChange], str]:
    """Optimize a single file's hotspots. Returns (file_path, changes, optimized_content)."""
    # Filter benchmark results to this file
    file_results = [r for r in benchmark_results if r.get("file") == file_path]

    agent = get_agent(OptimizationPlan, OPTIMIZER_PROMPT, GEMINI_PRO)

    hotspot_info = [
        {"function_name": h.function_name, "severity": h.severity,
         "category": h.category, "reasoning": h.reasoning}
        for h in hotspots
    ]

    prompt = f"""## Bottlenecks in {file_path}
```json
{json.dumps(hotspot_info, indent=2)}
```

## Benchmark Results
```json
{json.dumps(file_results, indent=2)}
```

## Source File: {file_path}
```
{file_content[:8000]}
```

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

    # Group hotspots by file
    file_hotspots: dict[str, list[Hotspot]] = {}
    for hotspot in analysis.hotspots:
        file_hotspots.setdefault(hotspot.file, []).append(hotspot)

    # Read affected files
    affected_files: dict[str, str] = {}
    for file_path in file_hotspots:
        try:
            affected_files[file_path] = read_file(repo_path, file_path)
        except Exception as e:
            log.warning("optimize_read_file_failed", file=file_path, error=str(e))

    log.info(
        "optimize_start",
        num_hotspots=len(analysis.hotspots),
        num_files=len(affected_files),
        affected_files=list(affected_files.keys()),
    )

    # Optimize each file in parallel
    tasks = [
        _optimize_file(file_path, content, file_hotspots[file_path], initial_results)
        for file_path, content in affected_files.items()
    ]
    results = await asyncio.gather(*tasks)

    optimized_files = {}
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
