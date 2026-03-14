import json

import structlog

from agent.schemas import AnalysisResult, OptimizationPlan
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged
from services.github_service import read_file

log = structlog.get_logger()

OPTIMIZER_PROMPT = """You are an elite performance optimization engineer. Given:
1. Analysis of performance bottlenecks with severity and reasoning
2. Benchmark results showing actual timing/memory data
3. The source code of affected files

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


async def optimize_node(state: AgentState) -> dict:
    """Generate optimized code for identified bottlenecks."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    initial_results = state.get("initial_results", [])
    repo_path = state.get("repo_path", "")

    affected_files = {}
    for hotspot in analysis.hotspots:
        if hotspot.file not in affected_files:
            try:
                affected_files[hotspot.file] = read_file(repo_path, hotspot.file)
            except Exception as e:
                log.warning("optimize_read_file_failed", file=hotspot.file, error=str(e))

    log.info(
        "optimize_start",
        num_hotspots=len(analysis.hotspots),
        affected_files=list(affected_files.keys()),
        affected_file_sizes={k: len(v) for k, v in affected_files.items()},
    )

    agent = get_agent(OptimizationPlan, OPTIMIZER_PROMPT, GEMINI_PRO)

    prompt = f"""## Bottleneck Analysis
```json
{json.dumps(analysis.model_dump(), indent=2)}
```

## Benchmark Results
```json
{json.dumps(initial_results, indent=2)}
```

## Affected Source Files
"""
    for path, content in affected_files.items():
        prompt += f"\n### {path}\n```\n{content[:5000]}\n```\n"

    result = await run_agent_logged(agent, prompt, node_name="optimize")
    plan: OptimizationPlan = result.output  # type: ignore[assignment]

    for change in plan.changes:
        log.info(
            "optimization_change",
            file=change.file,
            function=change.function_name,
            explanation=change.explanation[:200],
            expected_improvement=change.expected_improvement,
            original_chars=len(change.original_snippet),
            optimized_chars=len(change.optimized_snippet),
        )

    optimized_files = dict(affected_files)
    for change in plan.changes:
        if change.file in optimized_files:
            optimized_files[change.file] = optimized_files[change.file].replace(
                change.original_snippet, change.optimized_snippet
            )

    log.info(
        "optimize_complete",
        changes=len(plan.changes),
        files_modified=len(optimized_files),
        summary=plan.summary[:200],
    )

    return {
        **state,
        "optimized_files": optimized_files,
        "messages": state.get("messages", []) + [
            f"Generated {len(plan.changes)} optimizations"
        ],
    }
