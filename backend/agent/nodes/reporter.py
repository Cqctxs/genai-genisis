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
        initial_summary=[
            {"fn": r.get("function_name"), "time_ms": r.get("avg_time_ms"), "mem_mb": r.get("memory_peak_mb")}
            for r in initial_results
        ],
        final_summary=[
            {"fn": r.get("function_name"), "time_ms": r.get("avg_time_ms"), "mem_mb": r.get("memory_peak_mb")}
            for r in final_results
        ],
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
        score_before=report.codemark_score.overall_before,
        score_after=report.codemark_score.overall_after,
        time_score=report.codemark_score.time_score,
        memory_score=report.codemark_score.memory_score,
        complexity_score=report.codemark_score.complexity_score,
        functions_compared=len(report.functions),
        summary=report.summary[:200],
    )

    for fn in report.functions:
        log.info(
            "function_comparison",
            function=fn.function_name,
            file=fn.file,
            old_time_ms=fn.old_time_ms,
            new_time_ms=fn.new_time_ms,
            speedup=fn.speedup_factor,
            memory_reduction_pct=fn.memory_reduction_pct,
        )

    return {
        **state,
        "comparison": report.model_dump(),
        "messages": state.get("messages", []) + [
            f"CodeMark Score: {report.codemark_score.overall_before:.0f} -> {report.codemark_score.overall_after:.0f}"
        ],
    }
