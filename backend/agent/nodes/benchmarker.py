import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript, Hotspot, slim_ast_for_prompt
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

log = structlog.get_logger()

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of performance bottlenecks
in a codebase, generate profiling scripts that measure the execution time of each identified hotspot.

## Sandbox Environment

The benchmark script runs inside an isolated sandbox where:
- The repo's source files are available in the working directory (same layout as the repo).
- The repo's dependencies from requirements.txt / package.json ARE already installed.
- PYTHONPATH is set to the working directory, but for extra safety, **your Python benchmark script MUST begin with**:
  `import sys, os; sys.path.insert(0, os.getcwd())`
  This ensures the repo's local modules are always found before any system site-packages.
- You MUST import from the repo normally using the actual file path provided (e.g. if the File is `advanced_demo/analytics.py`, use `from advanced_demo.analytics import process_data` in Python or `require('./advanced_demo/analytics')` in JS).
- Do NOT use generic names like `from hotspot_1 import ...`. The file is named exactly what is passed in the "File:" field.
- Do NOT reimplement, inline, or stub out functions that exist in the repo.
- Do NOT call pip install or npm install — dependencies are pre-installed.
- If a function requires database connections, network I/O, or external services to run,
  create minimal mock/stub data so the function's core logic can still execute.
  **CRITICAL**: If you are mocking an I/O bound external call (like network or DB), your mock MUST include realistic artificial latency (e.g., `time.sleep(0.05)` or `await new Promise(r => setTimeout(r, 50))`) so concurrency optimizations can demonstrate actual speedup without pure CPU lock overhead.
- If you mock functions using `unittest.mock.patch`, you MUST import the module you are patching FIRST. (e.g. if you patch `advanced_demo.main.os.path.exists`, you MUST do `import advanced_demo.main` before the patch). Otherwise it will fail with AttributeError.
- **CRITICAL MOCK RULE**: If you use `unittest.mock.patch` or `MagicMock` to mock functions that are passed as arguments to other functions, you MUST explicitly assign a `__name__` attribute to the mock object (e.g., `mock_function.__name__ = 'my_function'`) to prevent `AttributeError` during introspection such as `func.__name__`.
- **PREFER REAL CODE OVER MOCKING**: Do NOT aggressively mock internal target functions. Always prefer executing the actual repository code. Only mock external dependencies (network, database, file system) that would hang or destroy the environment. Mocking the function you are benchmarking defeats the purpose of the benchmark.

## Rules

- Do NOT include any memory measurement code. No tracemalloc, no memory_profiler,
  no process.memoryUsage(). Memory is measured automatically by the runtime wrapper.
- Focus ONLY on timing and correctness fingerprinting.

## Correctness Fingerprinting (REQUIRED)

After timing, you MUST generate a `validation_fingerprint` to verify the function's output
has not changed. This is critical for detecting when optimizations break functionality.

1. Before the timing loop, call the function ONCE with a fixed, deterministic input.
2. Capture the return value (or the mutated state if the function returns void).
3. Serialize the result into a stable string representation.
   **IMPORTANT**: If the result is a large object (list/array/dict with >100 elements),
   TRUNCATE or SAMPLE it before serializing to avoid blocking CPU time:
   - For Python: `s = result[:100] if isinstance(result, (list, tuple)) else result;
     serialized = json.dumps(s, sort_keys=True, default=str)[:10000]`
   - For JavaScript: `let s = Array.isArray(result) ? result.slice(0, 100) : result;
     let serialized = JSON.stringify(s).slice(0, 10000)`
   This keeps fingerprinting under 1ms even for massive outputs.
4. Hash the serialized string to produce a short fingerprint:
   - For Python: `import hashlib; fingerprint = hashlib.sha256(serialized.encode()).hexdigest()[:16]`
   - For JavaScript: use `require('crypto').createHash('sha256').update(serialized).digest('hex').slice(0, 16)`
5. Include the fingerprint in the output JSON as `"validation_fingerprint": "<hex_string>"`.

DETERMINISM RULES:
- If the function uses randomness, seed the RNG before the fingerprint call (e.g. Math.random seed, random.seed(42)).
- If the function uses Date/time, mock it to a fixed value.
- If the function reads from network/DB, use the same mock data.
- The fingerprint MUST be identical across runs with the same code. If it is not deterministic, the system will incorrectly flag the optimization as broken.

## PREVENTING DEAD CODE ELIMINATION (CRITICAL)

JavaScript V8 and Python compilers aggressively optimize away function calls whose return
values are never used. If you do NOT follow these rules, your benchmark will report 0.00ms
because the engine literally deletes the code.

1. ALWAYS capture the return value of EVERY function call inside the timing loop.
2. Accumulate results into a variable that PERSISTS across iterations (e.g. a checksum,
   an XOR hash, or append to an array).
3. AFTER the timing loop, PRINT or USE the accumulated result so the engine cannot
   prove the computation is dead.

### JavaScript anti-DCE pattern (REQUIRED):
```javascript
let _checksum = 0;
const start = performance.now();
for (let i = 0; i < iterations; i++) {
    const result = targetFunction(testData);
    // Use a CHEAP accumulator — avoid JSON.stringify inside the loop!
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
    # Use a CHEAP accumulator — avoid str(result) or json.dumps inside the loop!
    _checksum += len(result) if hasattr(result, '__len__') else (result if isinstance(result, (int, float)) else 1)
elapsed = time.perf_counter() - start
assert _checksum >= 0, _checksum
```

IMPORTANT: The anti-DCE accumulator MUST be cheap (O(1) per iteration). NEVER call
`JSON.stringify`, `str()`, `json.dumps`, or `len(str(result))` inside the timing loop — these
serialization calls can dominate execution time for functions returning large objects, making
the benchmark measure serialization cost instead of the actual function.

## NON-UNIFORM MOCK DATA (REQUIRED)

Runtime engines (V8, CPython) aggressively optimize arrays filled with identical values.
To capture real-world performance, ALL generated test data MUST have high variance:

- Seed a PRNG for reproducibility (Python: `random.seed(42)`, JS: use a simple LCG or `seedrandom`).
- For numeric arrays: generate values with `(i * 2654435761) % N` or `random.randint(0, N)`.
  NEVER use `[0] * N`, `Array(N).fill(0)`, or any constant-fill pattern.
- For string arrays: vary lengths and characters, e.g. `chr(65 + i % 26) * (i % 20 + 1)`.
- For dicts/objects: use varied keys AND values; do not repeat identical entries.
- For nested structures: vary inner sizes, not just the outer container.

Bad  (uniform): `data = [1] * 10000`
Good (varied):  `random.seed(42); data = [random.randint(0, 100000) for _ in range(10000)]`

Bad  (uniform): `const data = Array(10000).fill({key: "a", val: 1})`
Good (varied):  `const data = Array.from({length: 10000}, (_, i) => ({key: "k" + ((i * 2654435761) >>> 0) % 10000, val: i * 7 % 9973}))`

## DYNAMIC ITERATION SCALING (REQUIRED)

Do NOT hardcode the number of iterations. Use a dynamic formula that targets ~4 seconds of total timing:

1. Run the function ONCE as a warmup and measure `single_call_ms`.
2. Compute iterations dynamically:
   - Python:  `iterations = max(5, int(4000 / single_call_ms))`
   - JavaScript:  `const iterations = Math.max(5, Math.floor(4000 / single_call_ms))`
3. This automatically adapts: fast functions get many iterations, slow ones get few.
4. Ensure total estimated runtime stays heavily under 10 seconds.
5. The reported avg_time_ms MUST be > 0.001. If it rounds to 0, increase input size.

## INPUT SIZE — COMPLEXITY-AWARE BOUNDS (CRITICAL)

Choose input sizes based on the algorithmic complexity of the function being benchmarked.
The script runs under a hard 15-second timeout, so quadratic or worse algorithms with large
inputs will crash before any iterations run.

### O(1) / O(log n) — constant or logarithmic:
- N = 50,000+ is fine. Prefer 50,000.

### O(n) / O(n log n) — linear or linearithmic:
- N = 10,000 minimum, 50,000 preferred.

### O(n²) — quadratic (nested loops, bubble sort, etc.):
- N = 500–1,000 MAXIMUM. Values above 1,000 will exceed the timeout.
- Prefer N = 700 as a balance between measurability and safety.

### O(n³) or worse — cubic / exponential:
- N = 100–300 MAXIMUM. Keep it small enough for a single call to finish in < 1 second.

### General rules:
- For map/dict lookups (O(1) amortised): N = 50,000+ entries.
- For I/O-bound code: simulate at least 20 sequential operations.
- For string operations on linear algorithms: use strings of 10,000+ characters.
- NEVER use trivially small inputs (N < 50). Small inputs hide algorithmic improvements
  behind constant-factor overhead and produce misleading benchmark results.
- When in doubt about the complexity, start with N = 1,000 and verify the warmup call
  finishes well under 2 seconds. If it takes longer, reduce N.

## Output Format

For Python: Use time.perf_counter() or timeit to measure execution time. Write scripts that
import the target functions from the repo, set up realistic-sized test data (see INPUT SIZE above),
and output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100, "validation_fingerprint": "abcd1234"}

For JavaScript/TypeScript: Use require() (CommonJS) NOT import (ESM). The sandbox runs
scripts with plain `node` in CommonJS mode. Use `const { performance } = require("perf_hooks")`
for timing. Write scripts that require target functions from the repo, set up realistic-sized
test data (see INPUT SIZE above), and output a single JSON object on the LAST line of stdout:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100, "validation_fingerprint": "abcd1234"}

Any debug/progress output must go to stderr or earlier stdout lines — the LAST line of stdout
must be the JSON result object and nothing else."""


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
