import asyncio
import json

import structlog
from pydantic import BaseModel

from agent.schemas import CodeMarkScore, ComparisonReport, FunctionComparison
from agent.state import AgentState
from services.modal_service import get_sandbox_specs
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged
from services.scoring_service import compute_benchy_score

log = structlog.get_logger()

SUMMARY_PROMPT = """You are a concise technical writer. Given the benchmark comparison data below,
write a short summary (3-5 sentences) explaining what optimizations were applied, how they
affected performance, and whether any time-space tradeoffs were made.

Do NOT invent numbers — only reference the data provided. Be direct and factual."""

SUMMARY_TIMEOUT_S = 30


class SummaryText(BaseModel):
    summary: str


async def report_node(state: AgentState) -> dict:
    """Calculate CodeMark score deterministically, then ask LLM only for summary text."""
    initial_results = state.get("initial_results", [])
    final_results = state.get("final_results", [])
    hotspots = state.get("analysis", {}).get("hotspots", [])

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
