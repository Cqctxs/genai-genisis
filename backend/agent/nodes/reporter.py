import asyncio
import json

import structlog
from pydantic import BaseModel

from agent.schemas import CodeMarkScore, ComparisonReport, FunctionComparison, BenchmarkDetail
from agent.state import AgentState
from services.modal_service import get_sandbox_specs
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged
from services.scoring_service import compute_benchy_score

log = structlog.get_logger()

SUMMARY_PROMPT = """You are a concise technical writer. Given the benchmark comparison data below,
write a short summary (3-5 sentences) explaining what optimizations were applied, how they
affected performance, and whether any time-space tradeoffs were made.

Do NOT invent numbers — only reference the data provided. Be direct and factual."""

BENCHMARK_DETAIL_PROMPT = """You are a concise technical writer. Summarize what this benchmark tests in 1-2 sentences.
Focus on: what the function does, what the test measures, what changed between before and after.
Be specific and technical but concise."""

SUMMARY_TIMEOUT_S = 30


class SummaryText(BaseModel):
    summary: str


async def report_node(state: AgentState) -> dict:
    """Calculate CodeMark score deterministically, then ask LLM only for summary text."""
    initial_results = state.get("initial_results", [])
    final_results = state.get("final_results", [])
    hotspots = state.get("analysis", {}).get("hotspots", [])
    benchmark_code = state.get("benchmark_code", [])

    log.info(
        "report_start",
        initial_results_count=len(initial_results),
        final_results_count=len(final_results),
        initial_total_ms=round(sum(r.get("avg_time_ms", 0) for r in initial_results), 1),
        final_total_ms=round(sum(r.get("avg_time_ms", 0) for r in final_results), 1),
        hotspots_count=len(hotspots),
    )

    score, function_comparisons = compute_benchy_score(
        initial_results, final_results, hotspots,
    )

    sandbox_specs = await get_sandbox_specs()
    summary = await _generate_summary(function_comparisons, hotspots, score)

    # Generate detailed benchmark information
    benchmark_details = await _generate_benchmark_details(
        benchmark_code, initial_results, final_results, function_comparisons
    )

    report = ComparisonReport(
        functions=function_comparisons,
        benchy_score=score,
        summary=summary,
        sandbox_specs=sandbox_specs,
    )

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
        "benchmark_details": [bd.model_dump() for bd in benchmark_details],
        "messages": state.get("messages", []) + [
            f"CodeMark Score: {report.benchy_score.overall_before:.0f} -> {report.benchy_score.overall_after:.0f}"
        ],
    }


async def _generate_summary(
    comparisons: list[FunctionComparison],
    hotspots: list[dict],
    score: CodeMarkScore,
) -> str:
    """Try LLM summary with a hard timeout; fall back to template on any failure."""
    comparison_data = [fc.model_dump() for fc in comparisons]

    agent = get_agent(SummaryText, SUMMARY_PROMPT, GEMINI_FLASH)

    prompt = f"""## Benchmark Comparison
```json
{json.dumps(comparison_data, indent=2)}
```

## Hotspots Addressed
```json
{json.dumps(hotspots, indent=2)[:4000]}
```

## Score
Overall: {score.overall_before:.0f} → {score.overall_after:.0f}
Time: {score.time_score:.0f} | Memory: {score.memory_score:.0f} | Complexity: {score.complexity_score:.0f}

Write a concise summary of the optimizations and their impact."""

    try:
        result = await asyncio.wait_for(
            run_agent_logged(agent, prompt, node_name="report_summary"),
            timeout=SUMMARY_TIMEOUT_S,
        )
        summary_output: SummaryText = result.output  # type: ignore[assignment]
        return summary_output.summary
    except TimeoutError:
        log.warning("report_summary_timeout", timeout_s=SUMMARY_TIMEOUT_S)
    except Exception as e:
        log.warning("report_summary_llm_failed", error=str(e))

    return _fallback_summary(comparisons, score)


def _fallback_summary(
    comparisons: list[FunctionComparison],
    score: CodeMarkScore,
) -> str:
    """Template-based summary used when the LLM call fails or times out."""
    if not comparisons:
        return "No benchmark comparisons available."

    improved = [c for c in comparisons if c.speedup_factor > 1.05]
    tradeoffs = [c for c in comparisons if c.speedup_factor > 1.05 and c.memory_reduction_pct < -5]
    fn_names = ", ".join(c.function_name for c in comparisons)

    parts = [f"Analysed {len(comparisons)} function(s): {fn_names}."]
    if improved:
        avg_speedup = sum(c.speedup_factor for c in improved) / len(improved)
        parts.append(f"{len(improved)} showed measurable improvement (avg {avg_speedup:.1f}x speedup).")
    else:
        parts.append("Benchmark times were within noise margins on the sandbox's input sizes.")
    if tradeoffs:
        parts.append(f"{len(tradeoffs)} used a time-space tradeoff (faster execution, higher memory).")
    parts.append(f"Overall CodeMark score: {score.overall_before:.0f} → {score.overall_after:.0f}.")
    return " ".join(parts)


async def _generate_benchmark_details(
    benchmark_code: list[dict],
    initial_results: list[dict],
    final_results: list[dict],
    comparisons: list[FunctionComparison],
) -> list[BenchmarkDetail]:
    """Generate detailed benchmark information including summaries."""
    if not benchmark_code:
        return []

    # Map results by function name for quick lookup
    initial_by_fn = {r.get("function_name", ""): r for r in initial_results}
    final_by_fn = {r.get("function_name", ""): r for r in final_results}

    details = []
    agent = get_agent(SummaryText, BENCHMARK_DETAIL_PROMPT, GEMINI_FLASH)

    for bench in benchmark_code[:10]:  # Limit to first 10 benchmarks for performance
        fn_name = bench.get("target_function", "")
        initial = initial_by_fn.get(fn_name, {})
        final = final_by_fn.get(fn_name, {})

        # Find comparison for this function
        comparison = next((c for c in comparisons if c.function_name == fn_name), None)
        if not comparison:
            continue

        # Generate benchmark summary
        summary = ""
        try:
            summary_prompt = f"""This benchmark tests the function `{fn_name}` in file `{bench.get('file', '')}`.

The benchmark script:
```{bench.get('language', 'python')}
{bench.get('script_content', '')[:1000]}
```

Before optimization: {initial.get("avg_time_ms", 0):.2f}ms, {initial.get("memory_peak_mb", 0):.1f}MB
After optimization: {final.get("avg_time_ms", 0):.2f}ms, {final.get("memory_peak_mb", 0):.1f}MB

Summarize what this benchmark tests."""

            result = await asyncio.wait_for(
                run_agent_logged(agent, summary_prompt, node_name=f"benchmark_detail_{fn_name}"),
                timeout=10,
            )
            summary_output: SummaryText = result.output  # type: ignore[assignment]
            summary = summary_output.summary
        except Exception as e:
            log.warning("benchmark_detail_summary_failed", function=fn_name, error=str(e))
            summary = f"Benchmark for {fn_name}"

        detail = BenchmarkDetail(
            function_name=fn_name,
            file=bench.get("file", ""),
            language=bench.get("language", ""),
            script_content=bench.get("script_content", ""),
            before_time_ms=float(initial.get("avg_time_ms", 0)),
            before_memory_mb=float(initial.get("memory_peak_mb", 0)),
            after_time_ms=float(final.get("avg_time_ms", 0)),
            after_memory_mb=float(final.get("memory_peak_mb", 0)),
            speedup_factor=comparison.speedup_factor,
            summary=summary,
        )
        details.append(detail)

    return details
