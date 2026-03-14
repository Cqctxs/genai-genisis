import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript, Hotspot
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged

log = structlog.get_logger()

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of performance bottlenecks
in a codebase, generate profiling scripts that measure the execution time of each identified hotspot.

## Sandbox Environment

The benchmark script runs inside an isolated sandbox where:
- The repo's source files are available in the working directory (same layout as the repo).
- The repo's dependencies from requirements.txt / package.json ARE already installed.
- You MUST import from the repo normally (e.g. `from myapp.utils import process_data`).
- Do NOT reimplement, inline, or stub out functions that exist in the repo.
- Do NOT call pip install or npm install — dependencies are pre-installed.
- If a function requires database connections, network I/O, or external services to run,
  create minimal mock/stub data so the function's core logic can still execute.

## Rules

- Do NOT include any memory measurement code. No tracemalloc, no memory_profiler,
  no process.memoryUsage(). Memory is measured automatically by the runtime wrapper.
- Focus ONLY on timing.

## INPUT SIZE — THIS IS CRITICAL

- Use input sizes large enough to reveal algorithmic complexity differences.
- For array/list operations: N = 10 000 minimum (50 000 preferred).
- For nested loop / O(n²) patterns: N = 5 000–10 000 so quadratic cost is measurable.
- For map/dict lookups: N = 50 000+ entries.
- For I/O-bound code: simulate at least 20 sequential operations.
- For string operations: use strings of 10 000+ characters.
- NEVER use trivially small inputs (N < 100). Small inputs hide algorithmic improvements
  behind constant-factor overhead and produce misleading benchmark results.
- Run at least 50 iterations to get a stable average.

For Python: Use time.perf_counter() or timeit to measure execution time. Write scripts that
import the target functions from the repo, set up realistic-sized test data (see INPUT SIZE above),
run at least 50 iterations, and output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100}

For JavaScript/TypeScript: Use require() (CommonJS) NOT import (ESM). The sandbox runs
scripts with plain `node` in CommonJS mode. Use `const { performance } = require("perf_hooks")`
for timing. Write scripts that require target functions from the repo, set up realistic-sized
test data (see INPUT SIZE above), run at least 50 iterations, and output a single JSON object
on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100}

Any debug/progress output must go to stderr or earlier stdout lines — the LAST line of stdout
must be the JSON result object and nothing else."""


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
