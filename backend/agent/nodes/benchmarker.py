import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript, Hotspot
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged

log = structlog.get_logger()

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of a performance bottleneck
in a codebase, generate a profiling script that measures the performance of the identified hotspot.

For Python: Use pyinstrument for profiling. Write a script that imports the target function,
sets up minimal test data, and measures execution time and memory. Output timing in JSON format
to stdout like: {"function": "name", "avg_time_ms": 123.4, "memory_peak_mb": 45.6, "iterations": 100}

For JavaScript/TypeScript: Use require() for imports (NOT import syntax). Use performance.now() for timing.
Write a script that requires the target function, sets up test data, and outputs JSON results to stdout in the same format.
Node.js runs in CommonJS mode, so use require() not import statements.

The script should be self-contained and runnable. Include necessary requires and test data setup.
Print ONLY the JSON result object to stdout."""


async def _generate_single_benchmark(
    hotspot: Hotspot, language: str, ast_map: dict, index: int
) -> BenchmarkScript | None:
    """Generate a benchmark script for a single hotspot."""
    agent = get_agent(BenchmarkScript, BENCHMARK_PROMPT, GEMINI_PRO)

    # Filter AST to relevant file
    filtered_ast = {
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") == hotspot.file],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") == hotspot.file],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") == hotspot.file],
    }

    prompt = f"""## Hotspot
- Function: {hotspot.function_name}
- File: {hotspot.file}
- Severity: {hotspot.severity}
- Category: {hotspot.category}
- Reasoning: {hotspot.reasoning}

## AST Context (functions in this file)
```json
{json.dumps(filtered_ast, indent=2)[:3000]}
```

Generate a profiling script for this hotspot. The language is: {language}"""

    try:
        result = await run_agent_logged(agent, prompt, node_name=f"gen_bench_{index}")
        bench: BenchmarkScript = result.output  # type: ignore[assignment]
        log.info(
            "benchmark_script_generated",
            index=index,
            target=bench.target_function,
            file=bench.file,
            language=bench.language,
            script_chars=len(bench.script_content),
        )
        return bench
    except Exception as e:
        log.error("benchmark_generation_failed", hotspot=hotspot.function_name, error=str(e))
        return None


async def generate_benchmarks_node(state: AgentState) -> dict:
    """Generate benchmark scripts targeting identified hotspots in parallel."""
    analysis = AnalysisResult(**state.get("analysis", {}))
    ast_map = state.get("ast_map", {})

    log.info(
        "generate_benchmarks_start",
        num_hotspots=len(analysis.hotspots),
        language=analysis.language,
        targets=[h.function_name for h in analysis.hotspots],
    )

    tasks = [
        _generate_single_benchmark(hotspot, analysis.language, ast_map, i)
        for i, hotspot in enumerate(analysis.hotspots)
    ]
    results = await asyncio.gather(*tasks)

    benchmarks = [b.model_dump() for b in results if b is not None]

    log.info("generate_benchmarks_complete", count=len(benchmarks))

    return {
        **state,
        "benchmark_code": benchmarks,
        "messages": state.get("messages", []) + [
            f"Generated {len(benchmarks)} benchmark scripts"
        ],
    }
