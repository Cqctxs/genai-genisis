import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript, Hotspot, slim_ast_for_prompt
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

log = structlog.get_logger()

# --- Benchmark Prompt Components ---

PROMPT_SANDBOX = """## Sandbox Environment

The benchmark script runs inside an isolated sandbox where:
- The repo's source files are available in the working directory (same layout as the repo).
- The repo's dependencies are already installed. Do NOT call pip/npm install.
- PYTHONPATH is set, but for extra safety, **your Python benchmark script MUST begin with**:
  `import sys, os; sys.path.insert(0, os.getcwd())`
- You MUST import from the repo normally using the actual file path provided.
- If a function requires database connections or network I/O, create minimal mock data.
- **CRITICAL**: If you mock an I/O bound external call, your mock MUST include realistic artificial latency (e.g., `time.sleep(0.05)`) so concurrency optimizations can demonstrate actual speedup.
- **MOCK ATTRIBUTES**: If you use `unittest.mock.patch` or `MagicMock`, you MUST explicitly assign a `__name__` attribute to the mock object (e.g., `mock_func.__name__ = 'func'`) to prevent `AttributeError` during introspection.
- **PREFER REAL CODE OVER MOCKING**: Do NOT aggressively mock internal target functions. Always prefer executing the actual repository code.
- **FILE I/O IS FULLY ALLOWED**: The sandbox has a real filesystem. **Do NOT mock `open()`, `builtins.open`, or `fs`**. Creating, reading, and writing temporary files in the working directory is expected."""

PROMPT_RULES = """## Rules

- Do NOT include any memory measurement code. Memory is measured automatically by the runtime wrapper.
- Focus ONLY on timing and correctness fingerprinting."""

PROMPT_FINGERPRINT = """## Correctness Fingerprinting (REQUIRED)

After timing, you MUST generate a `validation_fingerprint` to verify the function's output:
1. Before the timing loop, call the function ONCE with a fixed, deterministic input.
2. Serialize the result (truncate/sample if >100 elements) into a stable string representation.
3. Hash it to produce a short fingerprint:
   - Python: `import hashlib; fingerprint = hashlib.sha256(serialized.encode()).hexdigest()[:16]`
   - JavaScript: `require('crypto').createHash('sha256').update(serialized).digest('hex').slice(0, 16)`
4. Include the fingerprint in the output JSON as `"validation_fingerprint": "<hex_string>"`.
5. Ensure DETERMINISM: Seed RNGs (random.seed(42), etc.) and mock Date/time."""

PROMPT_DCE = """## PREVENTING DEAD CODE ELIMINATION (CRITICAL)

Compilers aggressively optimize away function calls whose return values are never used.
1. ALWAYS capture the return value of EVERY function call inside the timing loop.
2. Accumulate results into a CHEAP variable that PERSISTS across iterations (e.g. a checksum or length).
3. AFTER the timing loop, PRINT or USE the accumulated result so the engine cannot prove the computation is dead.

### JavaScript anti-DCE pattern (REQUIRED):
```javascript
let _checksum = 0;
const start = performance.now();
for (let i = 0; i < iterations; i++) {
    const result = targetFunction(testData);
    _checksum += (typeof result === 'number' ? result : (Array.isArray(result) ? result.length : 1));
}
const elapsed = performance.now() - start;
if (_checksum === -Infinity) console.log(_checksum);
```

### Python anti-DCE pattern (REQUIRED):
```python
_checksum = 0
start = time.perf_counter()
for _ in range(iterations):
    result = target_function(test_data)
    _checksum += len(result) if hasattr(result, '__len__') else (result if isinstance(result, (int, float)) else 1)
elapsed = time.perf_counter() - start
assert _checksum >= 0, _checksum
```"""

PROMPT_MOCK_DATA = """## NON-UNIFORM MOCK DATA (REQUIRED)

ALL generated test data MUST have high variance to avoid engine optimizations:
- Seed a PRNG for reproducibility (random.seed(42)).
- For numeric arrays: generate values with `random.randint` or LCG formulas. NEVER use constant-fill patterns.
- For objects/dicts: use varied keys and values."""

PROMPT_SCALING = """## DYNAMIC ITERATION SCALING (REQUIRED)

Do NOT hardcode the number of iterations. Target ~2 seconds of total timing:
1. Run the function ONCE as a warmup and measure `single_call_ms`.
2. Compute iterations: `iterations = max(5, int(2000 / single_call_ms))`.
3. Total estimated runtime MUST stay heavily under 10 seconds."""

PROMPT_INPUT_SIZE = """## INPUT SIZE — TIMEOUT SAFETY (CRITICAL)

The sandbox has a 30-second hard timeout. Algorithmic complexity determines N:
- **O(1) / O(log n)**: N = 20,000 - 50,000.
- **O(n) / O(n log n)**: N = 5,000 - 10,000.
- **O(n²)** (Nested loops, bubble sort, etc.): **N = 300 - 500 MAXIMUM**.
- **O(n³)** or worse: **N = 50 - 150 MAXIMUM**.
- **String operations**: Max 5,000 characters.
- When in doubt, start with N = 400."""

PROMPT_OUTPUT = """## Output Format

Output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100, "validation_fingerprint": "abcd1234"}

For JS: use `require` (CommonJS), not `import` (ESM). The sandbox runs scripts with plain `node`."""

BENCHMARK_PROMPT = f"""You are a benchmarking expert. Given an analysis of performance bottlenecks
in a codebase, generate a separate self-contained profiling script for EACH identified hotspot.

{PROMPT_SANDBOX}

{PROMPT_RULES}

{PROMPT_FINGERPRINT}

{PROMPT_DCE}

{PROMPT_MOCK_DATA}

{PROMPT_SCALING}

{PROMPT_INPUT_SIZE}

{PROMPT_OUTPUT}
"""


async def _generate_single_benchmark(
    hotspot: Hotspot, language: str, ast_map: dict, index: int
) -> BenchmarkScript | None:
    """Generate a benchmark script for a single hotspot."""
    agent = get_agent(BenchmarkScript, BENCHMARK_PROMPT, GEMINI_FLASH)

    # Filter AST to relevant file and strip verbose fields
    filtered_ast = slim_ast_for_prompt({
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") == hotspot.file],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") == hotspot.file],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") == hotspot.file],
    })

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
