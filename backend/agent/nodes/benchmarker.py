import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent

log = structlog.get_logger()

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of performance bottlenecks
in a codebase, generate profiling scripts that measure the performance of each identified hotspot.

For Python: Use pyinstrument for profiling. Write scripts that import the target functions,
set up minimal test data, and measure execution time and memory. Output timing in JSON format
to stdout like: {"function": "name", "avg_time_ms": 123.4, "memory_peak_mb": 45.6, "iterations": 100}

For JavaScript/TypeScript: Use performance.now() for timing. Write scripts that import target
functions, set up test data, and output JSON results to stdout in the same format.

Each script should be self-contained and runnable. Include necessary imports and test data setup.
Print ONLY the JSON result object to stdout."""


async def generate_benchmarks_node(state: AgentState) -> dict:
    """Generate benchmark scripts targeting identified hotspots."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    ast_map = state.get("ast_map", {})

    agent = get_agent(list[BenchmarkScript], BENCHMARK_PROMPT, GEMINI_PRO)

    prompt = f"""## Analysis Results
{json.dumps(analysis.model_dump(), indent=2)}

## AST Map (functions available)
{json.dumps(ast_map, indent=2)[:5000]}

Generate a profiling script for each hotspot. The language is: {analysis.language}
"""

    log.info("generating_benchmarks", num_hotspots=len(analysis.hotspots))
    result = await agent.run(prompt)
    benchmarks_out: list[BenchmarkScript] = result.output  # type: ignore[assignment]

    benchmarks = [b.model_dump() for b in benchmarks_out]

    return {
        **state,
        "benchmark_code": benchmarks,
        "messages": state.get("messages", []) + [
            f"Generated {len(benchmarks)} benchmark scripts"
        ],
    }
