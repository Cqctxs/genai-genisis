import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged

log = structlog.get_logger()

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of performance bottlenecks
in a codebase, generate profiling scripts that measure the execution time of each identified hotspot.

IMPORTANT: Do NOT include any memory measurement code. No tracemalloc, no memory_profiler,
no process.memoryUsage(). Memory is measured automatically by the runtime sandbox wrapper.
Focus ONLY on timing.

For Python: Use time.perf_counter() or timeit to measure execution time. Write scripts that
import the target functions, set up minimal realistic test data, run multiple iterations, and
output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100}

For JavaScript/TypeScript: Use require() (CommonJS) NOT import (ESM). The sandbox runs
scripts with plain `node` in CommonJS mode. Use `const { performance } = require("perf_hooks")`
for timing. Write scripts that require target functions, set up test data, run multiple
iterations, and output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100}

Each script must be self-contained and runnable. Include all necessary imports and test data.
Any debug/progress output must go to stderr or earlier stdout lines — the LAST line of stdout
must be the JSON result object and nothing else."""


async def generate_benchmarks_node(state: AgentState) -> dict:
    """Generate benchmark scripts targeting identified hotspots."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    ast_map = state.get("ast_map", {})

    log.info(
        "generate_benchmarks_start",
        num_hotspots=len(analysis.hotspots),
        language=analysis.language,
        targets=[h.function_name for h in analysis.hotspots],
    )

    agent = get_agent(list[BenchmarkScript], BENCHMARK_PROMPT, GEMINI_PRO)

    prompt = f"""## Analysis Results
{json.dumps(analysis.model_dump(), indent=2)}

## AST Map (functions available)
{json.dumps(ast_map, indent=2)[:5000]}

Generate a profiling script for each hotspot. The language is: {analysis.language}
"""

    result = await run_agent_logged(agent, prompt, node_name="generate_benchmarks")
    benchmarks_out: list[BenchmarkScript] = result.output  # type: ignore[assignment]

    for i, bench in enumerate(benchmarks_out):
        log.info(
            "benchmark_script_generated",
            index=i,
            target=bench.target_function,
            file=bench.file,
            language=bench.language,
            script_chars=len(bench.script_content),
            script_preview=bench.script_content[:200].replace("\n", "\\n"),
        )

    benchmarks = [b.model_dump() for b in benchmarks_out]

    log.info("generate_benchmarks_complete", count=len(benchmarks))

    return {
        **state,
        "benchmark_code": benchmarks,
        "messages": state.get("messages", []) + [
            f"Generated {len(benchmarks)} benchmark scripts"
        ],
    }
