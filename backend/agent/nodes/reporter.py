import json

import structlog

from agent.schemas import ComparisonReport
from agent.state import AgentState
from services.modal_service import get_sandbox_specs
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

log = structlog.get_logger()

REPORTER_PROMPT = """You are a benchmark scoring judge. Given before/after benchmark results,
calculate a CodeMark score and generate a detailed comparison report.

Scoring rules:
- Overall score is 0-20000. A baseline unoptimized project starts around 5000-8000.
- Time score: faster execution = higher score (weight: 40%)
- Memory score: lower memory usage = higher score (weight: 30%)
- Complexity score: better algorithmic complexity = higher score (weight: 30%)

For the radar chart, normalize each axis to 0-100:
- I/O Speed: based on I/O-bound function improvements
- CPU Efficiency: based on CPU-bound function improvements
- Memory Footprint: based on memory reduction
- Concurrency: based on parallelism improvements
- Code Quality: based on structural improvements

Calculate speedup_factor as old_time / new_time for each function.
Calculate memory_reduction_pct as (old_memory - new_memory) / old_memory * 100."""


async def report_node(state: AgentState) -> dict:
    """Calculate CodeMark score and generate comparison report."""
    initial_results = state.get("initial_results", [])
    final_results = state.get("final_results", [])

    log.info(
        "report_start",
        initial_results_count=len(initial_results),
        final_results_count=len(final_results),
        initial_total_ms=round(sum(r.get("avg_time_ms", 0) for r in initial_results), 1),
        final_total_ms=round(sum(r.get("avg_time_ms", 0) for r in final_results), 1),
    )

    sandbox_specs = await get_sandbox_specs()

    agent = get_agent(ComparisonReport, REPORTER_PROMPT, GEMINI_FLASH)

    prompt = f"""## Baseline Benchmark Results
```json
{json.dumps(initial_results, indent=2)}
```

## Optimized Benchmark Results
```json
{json.dumps(final_results, indent=2)}
```

## Sandbox Environment
{sandbox_specs}

Calculate the CodeMark score and generate the full comparison report."""

    result = await run_agent_logged(agent, prompt, node_name="report")
    report: ComparisonReport = result.output  # type: ignore[assignment]
    report.sandbox_specs = sandbox_specs

    log.info(
        "report_complete",
        score_before=report.benchy_score.overall_before,
        score_after=report.benchy_score.overall_after,
        time_score=report.benchy_score.time_score,
        memory_score=report.benchy_score.memory_score,
        complexity_score=report.benchy_score.complexity_score,
        functions_compared=len(report.functions),
        summary=report.summary[:200],
    )

    if report.functions:
        best = max(report.functions, key=lambda f: f.speedup_factor)
        log.info(
            "report_functions_summary",
            functions_compared=len(report.functions),
            best_speedup=f"{best.function_name} ({best.speedup_factor:.1f}x)",
            avg_speedup=round(sum(f.speedup_factor for f in report.functions) / len(report.functions), 2),
        )

    return {
        **state,
        "comparison": report.model_dump(),
        "messages": state.get("messages", []) + [
            f"CodeMark Score: {report.benchy_score.overall_before:.0f} -> {report.benchy_score.overall_after:.0f}"
        ],
    }
