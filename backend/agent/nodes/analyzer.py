import asyncio
import json

import structlog

from agent.schemas import AnalysisResult, BenchmarkBatch, BenchmarkScript, Hotspot, TriageChunk, TriageResult
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, PRO_SETTINGS_MEDIUM, get_agent, run_agent_logged
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
- Missing caching opportunities
- Synchronous API calls that could be batched
- Large memory allocations in loops

Return a structured analysis with specific hotspots, their severity, and reasoning."""

BENCHMARK_PROMPT = """You are a benchmarking expert. Given one or more performance bottlenecks
in a codebase, generate a separate self-contained profiling script for EACH hotspot.

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
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") in chunk_file_set],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") in chunk_file_set],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") in chunk_file_set],
        "call_edges": ast_map.get("call_edges", []),
    }

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


BENCHMARK_BATCH_SIZE = 4


async def _generate_benchmark_batch(
    hotspots: list[Hotspot],
    language: str,
    ast_map: dict,
    batch_index: int,
) -> list[BenchmarkScript]:
    """Generate benchmark scripts for a batch of hotspots in a single API call."""
    agent = get_agent(BenchmarkBatch, BENCHMARK_PROMPT, GEMINI_FLASH)

    hotspot_sections = []
    for idx, hotspot in enumerate(hotspots):
        filtered_ast = {
            "functions": [f for f in ast_map.get("functions", []) if f.get("file") == hotspot.file],
            "classes": [c for c in ast_map.get("classes", []) if c.get("file") == hotspot.file],
            "imports": [imp for imp in ast_map.get("imports", []) if imp.get("file") == hotspot.file],
        }
        hotspot_sections.append(
            f"### Hotspot {idx + 1}\n"
            f"- Function: {hotspot.function_name}\n"
            f"- File: {hotspot.file}\n"
            f"- Severity: {hotspot.severity}\n"
            f"- Category: {hotspot.category}\n"
            f"- Reasoning: {hotspot.reasoning}\n\n"
            f"#### AST Context\n```json\n{json.dumps(filtered_ast, indent=2)[:3000]}\n```"
        )

    prompt = (
        f"Generate a profiling script for EACH of the following {len(hotspots)} hotspot(s).\n"
        f"Return exactly {len(hotspots)} BenchmarkScript object(s) in the `scripts` list.\n\n"
        f"The language is: {language}\n\n"
        + "\n\n".join(hotspot_sections)
    )

    try:
        result = await run_agent_logged(agent, prompt, node_name=f"gen_bench_batch_{batch_index}", model_settings=PRO_SETTINGS_MEDIUM)
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


async def chunk_analyze_node(state: AgentState) -> dict:
    """Analyze chunks in parallel (Flash), then generate benchmarks in batches (Flash)."""
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

    # Phase 1: Analyze all chunks in parallel (Flash)
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

    # Phase 2: Generate benchmarks in batches (Flash) — fewer API calls
    batches = [
        all_hotspots[i:i + BENCHMARK_BATCH_SIZE]
        for i in range(0, len(all_hotspots), BENCHMARK_BATCH_SIZE)
    ]
    log.info(
        "benchmark_generation_start",
        num_hotspots=len(all_hotspots),
        num_batches=len(batches),
        batch_sizes=[len(b) for b in batches],
    )

    batch_tasks = [
        _generate_benchmark_batch(batch, triage.language, ast_map, i)
        for i, batch in enumerate(batches)
    ]
    batch_results = await asyncio.gather(*batch_tasks)

    benchmarks = []
    for script_list in batch_results:
        benchmarks.extend([s.model_dump() for s in script_list])

    log.info("benchmark_generation_complete", count=len(benchmarks))

    log_block(
        "CHUNK ANALYZE SUMMARY",
        metadata={
            "analysis_model": GEMINI_FLASH,
            "chunks_analyzed": len(chunks),
            "hotspots_found": len(all_hotspots),
            "benchmark_batches": len(batches),
            "benchmark_scripts": len(benchmarks),
            "api_calls_saved": max(0, len(all_hotspots) - len(batches)),
        },
        color="cyan",
    )

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
