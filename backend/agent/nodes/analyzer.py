import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkScript, Hotspot, TriageChunk, TriageResult
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, GEMINI_PRO, get_agent, run_agent_logged
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
- Missing caching opportunities
- Synchronous API calls that could be batched
- Large memory allocations in loops

Return a structured analysis with specific hotspots, their severity, and reasoning."""

BENCHMARK_PROMPT = """You are a benchmarking expert. Given an analysis of a performance bottleneck
in a codebase, generate a profiling script that measures the performance of the identified hotspot.

CRITICAL SANDBOX CONSTRAINTS:
- The sandbox has NO external packages installed (no npm packages, no pip packages except pyinstrument/memory_profiler)
- For JavaScript: Do NOT require/import any external libraries (no react, lodash, express, etc.)
- You MUST inline or mock any external dependencies
- Only use Node.js built-in modules (fs, path, crypto, http, etc.)
- Copy the target function's source code directly into the benchmark script
- Create mock/stub data instead of importing real modules

For Python: Use pyinstrument for profiling. Copy the target function into the script,
set up minimal test data, and measure execution time and memory. Output timing in JSON format
to stdout like: {"function": "name", "avg_time_ms": 123.4, "memory_peak_mb": 45.6, "iterations": 100}

For JavaScript/TypeScript: Use require() for imports (NOT import syntax). Use performance.now() for timing.
Copy the target function into the script, set up mock test data, and output JSON results to stdout in the same format.
Node.js runs in CommonJS mode, so use require() not import statements.
Only require() Node.js built-in modules.

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
        "messages": state.get("messages", []) + [
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
        chunks=[{"id": c.chunk_id, "label": c.label, "files": len(c.files), "priority": c.priority} for c in triage.chunks],
    )

    return {
        **state,
        "triage_result": triage.model_dump(),
        "messages": state.get("messages", []) + [
            f"Triage: identified {len(triage.chunks)} code chunks across {triage.total_files_scanned} files"
        ],
    }


async def _analyze_chunk(
    chunk: TriageChunk,
    ast_map: dict,
    repo_path: str,
    language: str,
) -> list[Hotspot]:
    """Analyze a single chunk with Gemini Pro. Returns hotspots for this chunk."""
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
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") in chunk_file_set],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") in chunk_file_set],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") in chunk_file_set],
        "call_edges": ast_map.get("call_edges", []),
    }

    agent = get_agent(AnalysisResult, ANALYSIS_PROMPT, GEMINI_PRO)

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

    try:
        result = await run_agent_logged(agent, prompt, node_name=f"analyze_chunk_{chunk.chunk_id}")
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


async def _generate_single_benchmark(
    hotspot: Hotspot, language: str, ast_map: dict, index: int
) -> BenchmarkScript | None:
    """Generate a benchmark script for a single hotspot using Flash."""
    agent = get_agent(BenchmarkScript, BENCHMARK_PROMPT, GEMINI_FLASH)

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


async def chunk_analyze_node(state: AgentState) -> dict:
    """Analyze chunks in parallel (Pro), then generate benchmarks in parallel (Flash)."""
    triage_data = state.get("triage_result", {})
    triage = TriageResult(**triage_data)
    ast_map = state.get("ast_map", {})
    repo_path = state.get("repo_path", "")

    MAX_PARALLEL_CHUNKS = 5
    chunks = sorted(triage.chunks, key=lambda c: c.priority)[:MAX_PARALLEL_CHUNKS]

    log.info(
        "chunk_analyze_start",
        num_chunks=len(chunks),
        chunk_labels=[c.label for c in chunks],
    )

    # Phase 1: Analyze all chunks in parallel (Pro)
    analysis_tasks = [
        _analyze_chunk(chunk, ast_map, repo_path, triage.language)
        for chunk in chunks
    ]
    chunk_results = await asyncio.gather(*analysis_tasks)

    # Merge and deduplicate hotspots
    all_hotspots: list[Hotspot] = []
    seen: set[tuple[str, str]] = set()
    for hotspot_list in chunk_results:
        for hotspot in hotspot_list:
            key = (hotspot.function_name, hotspot.file)
            if key not in seen:
                seen.add(key)
                all_hotspots.append(hotspot)

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

    log.info("chunk_analyze_complete", language=triage.language, hotspots=len(all_hotspots))

    # Phase 2: Generate benchmarks for all hotspots in parallel (Flash)
    log.info("benchmark_generation_start", num_hotspots=len(all_hotspots))

    bench_tasks = [
        _generate_single_benchmark(hotspot, triage.language, ast_map, i)
        for i, hotspot in enumerate(all_hotspots)
    ]
    bench_results = await asyncio.gather(*bench_tasks)

    benchmarks = [b.model_dump() for b in bench_results if b is not None]

    log.info("benchmark_generation_complete", count=len(benchmarks))

    analysis = AnalysisResult(
        language=triage.language,
        hotspots=all_hotspots,
        summary=f"Analyzed {len(chunks)} code chunks in parallel. Found {len(all_hotspots)} hotspots.",
    )

    return {
        **state,
        "analysis": analysis.model_dump(),
        "benchmark_code": benchmarks,
        "messages": state.get("messages", []) + [
            f"Deep analysis: found {len(all_hotspots)} hotspots across {len(chunks)} chunks",
            f"Generated {len(benchmarks)} benchmark scripts",
        ],
    }
