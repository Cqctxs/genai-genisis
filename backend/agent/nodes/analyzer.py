import asyncio
import json

import structlog

from agent.schemas import (
    AnalysisResult,
    BenchmarkBatch,
    BenchmarkScript,
    Hotspot,
    TriageChunk,
    TriageResult,
)
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged
from services.log_utils import log_block
from services.github_service import get_file_tree, read_file
from services.parser_service import parse_repo

log = structlog.get_logger()

TRIAGE_PROMPT = """You are a senior performance engineer doing a QUICK triage scan of a codebase.
You are given the full AST map (all functions, classes, imports, and call edges).

Your job is to:
1. Identify the programming language
2. Group the source files into logical CHUNKS of 3-8 files each, based on:
   - Directory structure (files in the same directory)
   - Import relationships (files that import from each other)
   - Call graph clusters (functions that call each other)
   - Functional domain (e.g., "database layer", "API handlers", "data processing")
3. Assign each chunk a priority (1 = most likely to contain performance bottlenecks)
4. Prioritize chunks that contain:
   - Database/ORM code
   - Network/API calls
   - Data processing loops
   - File I/O operations
   - Recursive algorithms

Return 3-6 chunks covering the most important files. You do NOT need to include every file -
focus on files likely to contain performance-relevant code. Skip test files, config files, etc."""

ANALYSIS_PROMPT = """You are a senior performance engineer. You are given:
1. An AST map of a codebase (functions, classes, imports, call edges)
2. The source code of key files

Your job is to identify performance bottlenecks. Look for:
- N+1 query patterns
- Blocking I/O in async code
- O(n^2) or worse algorithms
- Unnecessary repeated computation
  - Missing caching opportunities (specifically for external API boundaries)
  - Synchronous API calls that could be batched or omitted entirely

CRITICAL CONSTRAINTS FOR YOUR ANALYSIS:
1. Context matters: If a program operates on a single input or does not naturally involve external I/O (e.g., pure computation or data transformation), DO NOT suggest I/O concurrency or batching optimizations. Focus instead on algorithmic complexity, memory footprint, reducing unnecessary allocations, and data structure choices.
2. Conversely, for programs that handle many external inputs or make network/DB requests, heavily prioritize async/concurrent I/O, connection pooling, and batching.
3. Be aware of the data size and iteration context. Algorithmic regressions matter primarily for large N. Focus on optimizing operations within very hot loops or processing large files/streams.
4. Functionality parity: Only identify hotspots and suggest optimizations that can be fixed WITHOUT altering the exact functional behavior, return types, or edge cases of the original code.

Return a structured analysis with specific hotspots, their severity, and reasoning."""

BENCHMARK_PROMPT = """You are a benchmarking expert. Given one or more performance bottlenecks
in a codebase, generate a separate self-contained profiling script for EACH hotspot.

CRITICAL SANDBOX CONSTRAINTS:
- The sandbox has common packages pre-installed (see list below), but you should
  STILL prefer inlining or mocking over importing when the dependency isn't essential
  to measuring the hotspot's algorithmic performance.
- Pre-installed Python packages: numpy, pandas, requests, aiohttp, pydantic, sqlalchemy,
  fastapi, flask, django, celery, redis, httpx, beautifulsoup4, lxml, pillow, scipy,
  scikit-learn, pytest, pyinstrument, memory_profiler.
- Pre-installed Node.js packages (available via require()): lodash, express, react,
  react-dom, next, axios, framer-motion, zod, typescript, ts-node, jest, mocha, chai,
  mongoose, pg, knex, sequelize, prisma, socket.io, ws, jsonwebtoken, bcrypt, uuid,
  dayjs, moment, date-fns, cheerio, node-fetch, @tanstack/react-query, swr.
- If a dependency is NOT in the pre-installed list above, you MUST mock/stub it.
  Do NOT run `npm install`, `pip install`, or any package manager commands in the script.
  Doing so will crash the container.
- You MUST import the target function from the repo using the exact file path provided in the "File:" section. For instance, if the file is `advanced_demo/data_generator.py`, use `from advanced_demo.data_generator import function_name` in Python or `require('./advanced_demo/data_generator')` in JS. Do NOT use fake names like `from hotspot_1`.
- **FILE I/O IS ALLOWED**: The sandbox has an ephemeral filesystem. **Do NOT mock `open()` or `builtins.open`** or filesystem operations (e.g. `fs.writeFileSync`). Creating, reading, and writing temporary files in the working directory is expected and required for accurate I/O benchmarking.
- Create mock/stub data instead of importing real modules when measuring pure logic.
- If you mock functions using `unittest.mock.patch`, you MUST import the module you are patching FIRST. (e.g. if you patch `advanced_demo.main.os.path.exists`, you MUST do `import advanced_demo.main` before the patch). Otherwise it will fail with AttributeError.
  CRITICAL JSON & ESCAPING CONSTRAINTS:
  - Do NOT generate ANY docstrings or comments inside the Python/JS code.
  - Do NOT use triple quotes (`\"\"\"` or `'''`) anywhere in the script to prevent JSON deserialization syntax errors.
  - Prefer single quotes (`'`) over double quotes (`"`) for standard strings to minimize escaping issues.
INPUT SIZE — THIS IS CRITICAL:
- Use input sizes large enough to reveal algorithmic complexity differences.
- For array/list operations: N = 10 000 minimum (50 000 preferred).
- For nested loop / O(n²) patterns: N = 5 000–10 000 so quadratic cost is measurable.
- For map/dict lookups: N = 50 000+ entries.
- For I/O-bound code: simulate at least 20 sequential operations.
- For string operations: use strings of 10 000+ characters.
- NEVER use trivially small inputs (N < 100). Small inputs hide algorithmic improvements
  behind constant-factor overhead and produce misleading benchmark results.
- TOTAL SCRIPT EXECUTION MUST COMPLETE WITHIN 30 SECONDS. If the function is slow,
  reduce the number of iterations (minimum 5) or input size until total runtime stays under 30s.
  Use a warm-up call to estimate per-call cost, then choose iterations accordingly.

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
    _checksum += (typeof result === 'object' ? JSON.stringify(result).length : Number(result)) || 1;
}
const elapsed = performance.now() - start;
// Anti-DCE anchor — do NOT remove
if (_checksum === -Infinity) console.log(_checksum);
```

### Python anti-DCE pattern (REQUIRED):
```python
_checksum = 0
start = time.perf_counter()
for _ in range(iterations):
    result = target_function(test_data)
    _checksum += len(str(result)) if result is not None else 1
elapsed = time.perf_counter() - start
# Anti-DCE anchor
assert _checksum >= 0, _checksum
```

## DYNAMIC ITERATION SCALING (REQUIRED)

Do NOT hardcode the number of iterations. Use this pattern:
1. Run the function ONCE as a warmup and measure the single-call time.
2. If single_call < 0.1ms: use 10,000 iterations
3. If single_call < 1ms: use 5,000 iterations
4. If single_call < 10ms: use 500 iterations
5. If single_call < 100ms: use 50 iterations
6. If single_call >= 100ms: use 10 iterations
7. Ensure total estimated runtime stays under 25 seconds.
8. The reported avg_time_ms MUST be > 0.001. If it rounds to 0, increase input size.

For Python: Use time.perf_counter() for timing. Copy the target function into the script,
set up realistic-sized test data (see INPUT SIZE above), and measure execution time.
Output timing in JSON format to stdout like:
{"function": "name", "avg_time_ms": 123.4, "iterations": 100}

For JavaScript/TypeScript: Use require() for imports (NOT import syntax). Use performance.now() for timing.
Copy the target function into the script, set up realistic-sized test data (see INPUT SIZE above),
and output JSON results to stdout in the same format.
Node.js runs in CommonJS mode, so use require() not import statements.
Only require() Node.js built-in modules.

Do NOT include any memory measurement code. Memory is measured automatically by the runtime wrapper.

The script must be completely self-contained - copy function code inline, mock all dependencies.
Print ONLY the JSON result object to stdout."""


async def parse_ast_node(state: AgentState) -> dict:
    """Extract AST data from the repository using tree-sitter."""
    repo_path = state.get("repo_path", "")
    file_tree = get_file_tree(repo_path)

    log.info("parse_ast_start", num_files=len(file_tree), files_sample=file_tree[:10])
    ast_data = await asyncio.to_thread(parse_repo, repo_path, file_tree)

    log.info(
        "parse_ast_complete",
        functions=len(ast_data.functions),
        classes=len(ast_data.classes),
        imports=len(ast_data.imports),
        call_edges=len(ast_data.call_edges),
    )

    return {
        **state,
        "file_tree": file_tree,
        "ast_map": ast_data.model_dump(),
        "messages": state.get("messages", [])
        + [
            f"Parsed {len(ast_data.functions)} functions, {len(ast_data.classes)} classes across {len(file_tree)} files"
        ],
    }


async def triage_node(state: AgentState) -> dict:
    """Use Gemini Flash for quick codebase triage and chunking."""
    ast_map = state.get("ast_map", {})

    log.info("triage_start", ast_keys=list(ast_map.keys()))

    agent = get_agent(TriageResult, TRIAGE_PROMPT, GEMINI_FLASH)

    prompt = f"""## Full AST Map
```json
{json.dumps(ast_map, indent=2)[:15000]}
```

Scan this codebase and group files into priority-ranked chunks for deep performance analysis."""

    result = await run_agent_logged(agent, prompt, node_name="triage")
    triage: TriageResult = result.output  # type: ignore[assignment]

    log.info(
        "triage_complete",
        language=triage.language,
        num_chunks=len(triage.chunks),
        chunks=[
            {
                "id": c.chunk_id,
                "label": c.label,
                "files": len(c.files),
                "priority": c.priority,
            }
            for c in triage.chunks
        ],
    )

    return {
        **state,
        "triage_result": triage.model_dump(),
        "messages": state.get("messages", [])
        + [
            f"Triage: identified {len(triage.chunks)} code chunks across {triage.total_files_scanned} files"
        ],
    }


async def _analyze_chunk(
    chunk: TriageChunk,
    ast_map: dict,
    repo_path: str,
    language: str,
) -> list[Hotspot]:
    """Analyze a single chunk with Gemini Flash. Returns hotspots for this chunk."""
    chunk_files = {}
    for f in chunk.files:
        try:
            content = read_file(repo_path, f)
            if len(content) < 15000:
                chunk_files[f] = content
        except Exception:
            pass

    if not chunk_files:
        log.warning("chunk_no_files", chunk_id=chunk.chunk_id)
        return []

    chunk_file_set = set(chunk.files)
    filtered_ast = {
        "functions": [
            f for f in ast_map.get("functions", []) if f.get("file") in chunk_file_set
        ],
        "classes": [
            c for c in ast_map.get("classes", []) if c.get("file") in chunk_file_set
        ],
        "imports": [
            i for i in ast_map.get("imports", []) if i.get("file") in chunk_file_set
        ],
        "call_edges": ast_map.get("call_edges", []),
    }

    # When target_functions is set, filter AST to only those functions
    # and add guidance so the LLM focuses exclusively on them.
    target_fn_set = set(chunk.target_functions) if chunk.target_functions else None
    if target_fn_set:
        filtered_ast["functions"] = [
            f for f in filtered_ast["functions"] if f.get("name") in target_fn_set
        ]

    agent = get_agent(AnalysisResult, ANALYSIS_PROMPT, GEMINI_FLASH)

    prompt = f"""## Chunk: {chunk.label} (Priority: {chunk.priority})
Triage reasoning: {chunk.reasoning}

## AST Map (filtered to this chunk)
```json
{json.dumps(filtered_ast, indent=2)[:8000]}
```

## Source Files
"""
    for path, content in chunk_files.items():
        prompt += f"\n### {path}\n```\n{content[:5000]}\n```\n"

    prompt += f"\nThe language is: {language}"

    if target_fn_set:
        prompt += (
            f"\n\nIMPORTANT: Focus your analysis ONLY on these specific functions: "
            f"{', '.join(target_fn_set)}. "
            f"These were explicitly selected by the user for optimization. "
            f"Do NOT report hotspots for other functions in these files."
        )

    try:
        result = await run_agent_logged(
            agent, prompt, node_name=f"analyze_chunk_{chunk.chunk_id}"
        )
        analysis: AnalysisResult = result.output  # type: ignore[assignment]
        log.info(
            "chunk_analyzed",
            chunk_id=chunk.chunk_id,
            hotspots=len(analysis.hotspots),
        )
        return analysis.hotspots
    except Exception as e:
        log.error("chunk_analysis_failed", chunk_id=chunk.chunk_id, error=str(e))
        return []


BENCHMARK_BATCH_SIZE = 4


async def _generate_benchmark_batch(
    hotspots: list[Hotspot],
    language: str,
    ast_map: dict,
    batch_index: int,
    repo_files: dict[str, str],
) -> list[BenchmarkScript]:
    """Generate benchmark scripts for a batch of hotspots in a single API call."""
    agent = get_agent(BenchmarkBatch, BENCHMARK_PROMPT, GEMINI_FLASH)

    hotspot_sections = []
    for idx, hotspot in enumerate(hotspots):
        filtered_ast = {
            "functions": [
                f for f in ast_map.get("functions", []) if f.get("file") == hotspot.file
            ],
            "classes": [
                c for c in ast_map.get("classes", []) if c.get("file") == hotspot.file
            ],
            "imports": [
                imp
                for imp in ast_map.get("imports", [])
                if imp.get("file") == hotspot.file
            ],
        }
        file_content = repo_files.get(hotspot.file, "(File content not found)")[:15000]
        hotspot_sections.append(
            f"### Hotspot {idx + 1}\n"
            f"- Function: {hotspot.function_name}\n"
            f"- File: {hotspot.file}\n"
            f"- Severity: {hotspot.severity}\n"
            f"- Category: {hotspot.category}\n"
            f"- Reasoning: {hotspot.reasoning}\n\n"
            f"#### Original File Content ({hotspot.file})\n```\n{file_content}\n```\n\n"
            f"#### AST Context\n```json\n{json.dumps(filtered_ast, indent=2)[:3000]}\n```"
        )

    prompt = (
        f"Generate a profiling script for EACH of the following {len(hotspots)} hotspot(s).\n"
        f"Return exactly {len(hotspots)} BenchmarkScript object(s) in the `scripts` list.\n\n"
        f"The language is: {language}\n\n" + "\n\n".join(hotspot_sections)
    )

    try:
        result = await run_agent_logged(
            agent, prompt, node_name=f"gen_bench_batch_{batch_index}"
        )
        batch: BenchmarkBatch = result.output  # type: ignore[assignment]
        log.info(
            "benchmark_batch_generated",
            batch_index=batch_index,
            requested=len(hotspots),
            generated=len(batch.scripts),
        )
        for script in batch.scripts:
            log.debug(
                "benchmark_script_generated",
                batch_index=batch_index,
                target=script.target_function,
                file=script.file,
                language=script.language,
                script_chars=len(script.script_content),
            )
        return batch.scripts
    except Exception as e:
        log.error("benchmark_batch_failed", batch_index=batch_index, error=str(e))
        return []


async def _process_chunk_stream(
    chunk: TriageChunk,
    ast_map: dict,
    repo_path: str,
    language: str,
    chunk_index: int,
    repo_files: dict[str, str],
) -> tuple[list[Hotspot], list[dict], list[dict]]:
    """Stream a single chunk through the full pipeline: analyze -> gen benchmarks -> run.

    Returns (hotspots, benchmark_scripts_dicts, benchmark_results).
    Each chunk is fully independent, enabling maximum parallelism.
    """
    from agent.nodes.runner import _execute_single_benchmark

    # Step 1: Analyze this chunk for hotspots
    hotspots = await _analyze_chunk(chunk, ast_map, repo_path, language)
    if not hotspots:
        return [], [], []

    log.info(
        "chunk_stream_analyzed",
        chunk_id=chunk.chunk_id,
        hotspots_found=len(hotspots),
    )

    # Step 2: Generate benchmarks for these hotspots
    benchmarks = await _generate_benchmark_batch(
        hotspots, language, ast_map, chunk_index, repo_files
    )
    if not benchmarks:
        return hotspots, [], []

    log.info(
        "chunk_stream_benchmarks_generated",
        chunk_id=chunk.chunk_id,
        benchmarks=len(benchmarks),
    )

    # Step 3: Run benchmarks immediately (don't wait for other chunks)
    bench_tasks = [
        _execute_single_benchmark(bench, i, repo_files, ast_map=ast_map)
        for i, bench in enumerate(benchmarks)
    ]
    results = list(await asyncio.gather(*bench_tasks))

    log.info(
        "chunk_stream_benchmarks_run",
        chunk_id=chunk.chunk_id,
        results=len(results),
        total_time_ms=round(sum(r.get("avg_time_ms", 0) for r in results), 1),
    )

    return hotspots, [b.model_dump() for b in benchmarks], results


async def chunk_analyze_node(state: AgentState) -> dict:
    """Streaming per-chunk pipeline: analyze -> gen benchmarks -> run, all in parallel.

    Each chunk independently flows through the full pipeline. Results are merged
    at the end. This overlaps LLM calls with Modal sandbox execution for maximum
    throughput.
    """
    triage_data = state.get("triage_result", {})
    triage = TriageResult(**triage_data)
    ast_map = state.get("ast_map", {})
    repo_path = state.get("repo_path", "")
    file_tree = state.get("file_tree", [])

    MAX_PARALLEL_CHUNKS = 5
    chunks = sorted(triage.chunks, key=lambda c: c.priority)[:MAX_PARALLEL_CHUNKS]

    log.info(
        "chunk_analyze_start",
        num_chunks=len(chunks),
        chunk_labels=[c.label for c in chunks],
        mode="streaming",
    )

    repo_files: dict[str, str] = {}
    for f in file_tree:
        try:
            repo_files[f] = read_file(repo_path, f)
        except Exception as e:
            log.warning("repo_file_read_failed", file=f, error=str(e))

    for manifest in ("requirements.txt", "package.json"):
        if manifest not in repo_files:
            try:
                repo_files[manifest] = read_file(repo_path, manifest)
            except Exception:
                pass

    stream_tasks = [
        _process_chunk_stream(chunk, ast_map, repo_path, triage.language, i, repo_files)
        for i, chunk in enumerate(chunks)
    ]
    stream_results = await asyncio.gather(*stream_tasks)

    all_hotspots: list[Hotspot] = []
    all_benchmarks: list[dict] = []
    all_results: list[dict] = []
    seen: set[tuple[str, str]] = set()

    seen_benchmarks: set[tuple[str, str]] = set()

    for hotspots, benchmarks, results in stream_results:
        for hotspot in hotspots:
            key = (hotspot.function_name, hotspot.file)
            if key not in seen:
                seen.add(key)
                all_hotspots.append(hotspot)

        for bench, result in zip(benchmarks, results):
            bench_key = (bench.get("target_function"), bench.get("file"))
            if bench_key not in seen_benchmarks:
                seen_benchmarks.add(bench_key)
                all_benchmarks.append(bench)
                all_results.append(result)

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_hotspots.sort(key=lambda h: severity_order.get(h.severity, 4))

    for hotspot in all_hotspots:
        log.info(
            "hotspot_found",
            function=hotspot.function_name,
            file=hotspot.file,
            severity=hotspot.severity,
            category=hotspot.category,
        )

    log_block(
        "CHUNK ANALYZE SUMMARY",
        metadata={
            "analysis_model": GEMINI_FLASH,
            "chunks_analyzed": len(chunks),
            "hotspots_found": len(all_hotspots),
            "benchmark_scripts": len(all_benchmarks),
            "initial_results": len(all_results),
            "mode": "streaming",
        },
        color="cyan",
    )

    analysis = AnalysisResult(
        language=triage.language,
        hotspots=all_hotspots,
        summary=f"Streamed {len(chunks)} chunks in parallel. Found {len(all_hotspots)} hotspots.",
    )

    return {
        **state,
        "analysis": analysis.model_dump(),
        "benchmark_code": all_benchmarks,
        "initial_results": all_results,
        "messages": state.get("messages", [])
        + [
            f"Streamed analysis: {len(all_hotspots)} hotspots across {len(chunks)} chunks",
            f"Generated and ran {len(all_benchmarks)} benchmarks",
        ],
    }
