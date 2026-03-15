import asyncio
import json
import os
import time
import traceback

import railtracks as rt
import structlog

from agent.nodes.analyzer import chunk_analyze_node, parse_ast_node, triage_node
from agent.nodes.optimizer import optimize_node
from agent.nodes.reporter import report_node
from agent.nodes.runner import run_benchmarks_node
from agent.nodes.visualizer import visualize_node, visualize_preview_node
from agent.schemas import GraphData, GraphNode, TriageChunk, TriageResult
from agent.state import AgentState
from services.github_pr_service import create_optimization_pr
from services.github_service import cleanup_repo, clone_repo
from services.log_utils import log_block

log = structlog.get_logger()

MAX_OPTIMIZATION_RETRIES = 2


def _revert_broken_files(state: AgentState) -> dict[str, str]:
    """Revert optimized files that failed correctness back to originals.

    Returns the cleaned optimized_files dict (broken files replaced with originals).
    """
    failures = state.get("correctness_failures", [])
    original_files = state.get("original_files", {})
    optimized_files = dict(state.get("optimized_files", {}))

    broken_files = {f["file"] for f in failures}
    for file_path in broken_files:
        if file_path in original_files:
            optimized_files[file_path] = original_files[file_path]
            log.info("correctness_reverted_file", file=file_path)
        else:
            optimized_files.pop(file_path, None)
            log.warning("correctness_revert_no_original", file=file_path)

    return optimized_files


def _should_stop_retrying(state: AgentState) -> tuple[bool, str]:
    """Decide whether to stop retrying and proceed to report.

    Returns (should_stop, reason).
    """
    initial = state.get("initial_results", [])
    final = state.get("final_results", [])
    retry_count = state.get("retry_count", 0)
    correctness_failures = state.get("correctness_failures", [])

    initial_total = sum(r.get("avg_time_ms", 0) for r in initial)
    final_total = sum(r.get("avg_time_ms", 0) for r in final)

    if correctness_failures and retry_count < MAX_OPTIMIZATION_RETRIES:
        failed_fns = [f["function_name"] for f in correctness_failures]
        return False, f"correctness failures in {failed_fns}, retrying optimization"

    if correctness_failures and retry_count >= MAX_OPTIMIZATION_RETRIES:
        return (
            True,
            "correctness failures remain after max retries, reverting broken files",
        )

    if retry_count >= MAX_OPTIMIZATION_RETRIES:
        return True, f"max retries reached ({retry_count})"

    if not initial or not final:
        return True, f"missing results (initial={len(initial)}, final={len(final)})"

    if initial_total == 0 and final_total == 0:
        return (
            True,
            "all benchmarks returned 0ms (likely sandbox failures), skipping retry",
        )

    if initial_total > 0 and final_total < initial_total:
        return (
            True,
            f"improvement detected ({initial_total:.1f}ms -> {final_total:.1f}ms)",
        )

    if initial_total > 0 and abs(final_total - initial_total) / initial_total < 0.05:
        return (
            True,
            f"marginal difference ({initial_total:.1f}ms -> {final_total:.1f}ms, <5%), not worth retrying",
        )

    return (
        False,
        f"no improvement ({initial_total:.1f}ms -> {final_total:.1f}ms), retrying",
    )


async def _generate_initial_benchmark_details(state: AgentState) -> dict:
    """Generate benchmark detail summaries early, in parallel with optimization."""
    from agent.nodes.reporter import _generate_benchmark_details
    from services.scoring_service import compute_benchy_score

    benchmark_code = state.get("benchmark_code", [])
    initial_results = state.get("initial_results", [])
    hotspots = state.get("analysis", {}).get("hotspots", [])

    if not benchmark_code or not initial_results:
        return {"benchmark_details": []}

    # Compute comparisons from initial results (before optimization)
    _, comparisons = compute_benchy_score(initial_results, initial_results, hotspots)

    # Generate summaries for initial benchmarks
    benchmark_details = await _generate_benchmark_details(
        benchmark_code, initial_results, initial_results, comparisons
    )

    return {"benchmark_details": [bd.model_dump() for bd in benchmark_details]}


async def _rerun_benchmarks(state: AgentState) -> dict:
    """Write optimized files to disk and re-run benchmarks."""
    repo_path = state.get("repo_path", "")
    optimized_files = state.get("optimized_files", {})

    log.info("rerun_benchmarks_start", num_optimized_files=len(optimized_files))

    original_files = dict(state.get("original_files", {}))
    if not original_files:
        for rel_path in optimized_files:
            full_path = os.path.join(repo_path, rel_path)
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    original_files[rel_path] = f.read()

    for rel_path, content in optimized_files.items():
        full_path = os.path.join(repo_path, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info("rerun_wrote_optimized_file", path=rel_path, chars=len(content))

    result = await run_benchmarks_node(
        {**state, "initial_results": state.get("initial_results", [])}
    )

    log.info("rerun_benchmarks_complete")

    return {
        "original_files": original_files,
        "final_results": result.get("final_results", result.get("initial_results", [])),
        "correctness_failures": result.get("correctness_failures", []),
        "retry_count": state.get("retry_count", 0) + 1,
        "messages": state.get("messages", []) + ["Re-ran benchmarks on optimized code"],
    }


async def _create_pr(state: AgentState) -> dict:
    """Create a GitHub PR with optimized code. Non-fatal on failure."""
    repo_url = state.get("repo_url", "")
    github_token = state.get("github_token", "")
    optimized_files = state.get("optimized_files", {})
    comparison = state.get("comparison", {})

    if not optimized_files:
        log.warning("create_pr_skipped", reason="no optimized files")
        return {
            "pr_url": "",
            "pr_status": "skipped",
            "pr_error": "No optimized files to create PR",
        }

    try:
        pr_url = await create_optimization_pr(
            repo_url=repo_url,
            github_token=github_token,
            optimized_files=optimized_files,
            comparison=comparison,
        )
        log.info("create_pr_complete", pr_url=pr_url)
        return {
            "pr_url": pr_url,
            "pr_status": "success",
            "pr_error": None,
            "messages": state.get("messages", []) + [f"Pull request created: {pr_url}"],
        }
    except Exception as e:
        error_str = str(e).lower()
        permission_keywords = (
            "permission",
            "403",
            "404",
            "not found",
            "push access",
            "write permission",
        )
        if isinstance(e, PermissionError) or any(
            kw in error_str for kw in permission_keywords
        ):
            pr_status = "permission_denied"
            pr_error = str(e)
        else:
            pr_status = "failed"
            pr_error = f"Failed to create pull request: {e}"

        tb = traceback.format_exc()
        log.error(
            "create_pr_failed",
            error=str(e)[:300],
            pr_status=pr_status,
            traceback=tb[-500:] if len(tb) > 500 else tb,
        )
        return {
            "pr_url": "",
            "pr_status": pr_status,
            "pr_error": pr_error,
            "messages": state.get("messages", []) + [pr_error],
        }


def node_based_chunking(state: AgentState) -> dict:
    """Build TriageResult from user-selected graph nodes instead of running LLM triage.

    Groups selected nodes by file and creates TriageChunk objects that
    chunk_analyze_node can consume directly.
    """
    selected_ids = set(state.get("selected_node_ids") or [])
    preview_graph = state.get("preview_graph_data") or {}
    ast_map = state.get("ast_map", {})

    graph_data = GraphData(**preview_graph) if preview_graph else GraphData(nodes=[], edges=[])
    selected_nodes = [n for n in graph_data.nodes if n.id in selected_ids]

    if not selected_nodes:
        log.warning("node_based_chunking_empty", reason="no selected nodes matched graph")
        selected_nodes = list(graph_data.nodes)

    # Detect language from AST functions or default
    functions = ast_map.get("functions", [])
    language = "python"
    if functions:
        sample_file = functions[0].get("file", "")
        if sample_file.endswith((".js", ".ts", ".jsx", ".tsx")):
            language = "javascript"

    # Group selected nodes by file
    file_groups: dict[str, list[GraphNode]] = {}
    for node in selected_nodes:
        file_groups.setdefault(node.file, []).append(node)

    # Create TriageChunk per file group
    chunks: list[TriageChunk] = []
    for i, (file_path, nodes) in enumerate(file_groups.items(), start=1):
        fn_names = [n.function_name or n.label for n in nodes]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        best_severity = min(
            (severity_order.get(n.severity or "low", 3) for n in nodes),
            default=3,
        )
        chunks.append(
            TriageChunk(
                chunk_id=f"node_chunk_{i}",
                label=f"Selected nodes in {file_path}",
                files=[file_path],
                priority=best_severity + 1,
                reasoning=f"User-selected functions: {', '.join(fn_names)}",
                target_functions=fn_names,
            )
        )

    chunks.sort(key=lambda c: c.priority)

    triage = TriageResult(
        language=language,
        chunks=chunks,
        total_files_scanned=len(file_groups),
        summary=f"Node-based chunking: {len(selected_nodes)} selected nodes across {len(file_groups)} files",
    )

    log.info(
        "node_based_chunking_complete",
        selected_nodes=len(selected_nodes),
        chunks=len(chunks),
        files=list(file_groups.keys()),
    )

    return {
        **state,
        "triage_result": triage.model_dump(),
        "messages": state.get("messages", [])
        + [f"Node-based chunking: {len(selected_nodes)} targets across {len(chunks)} chunks"],
    }


def _extract_result(state: AgentState) -> dict:
    """Extract the final result payload from the accumulated pipeline state."""
    initial_results = state.get("initial_results", [])
    final_results = state.get("final_results", [])
    comparison = state.get("comparison", {})

    initial_total = sum(r.get("avg_time_ms", 0) for r in initial_results)
    final_total = sum(r.get("avg_time_ms", 0) for r in final_results)
    score = comparison.get("benchy_score", {})

    log_block(
        "PIPELINE COMPLETE",
        metadata={
            "hotspots_found": len(state.get("analysis", {}).get("hotspots", [])),
            "files_optimized": len(state.get("optimized_files", {})),
            "benchmarks_before_ms": round(initial_total, 1),
            "benchmarks_after_ms": round(final_total, 1),
            "score_before": score.get("overall_before", "N/A"),
            "score_after": score.get("overall_after", "N/A"),
            "pr_url": state.get("pr_url", ""),
        },
        color="magenta",
    )

    return {
        "graph_data": state.get("graph_data", {}),
        "comparison": comparison,
        "benchmark_details": state.get("benchmark_details", []),
        "optimized_files": state.get("optimized_files", {}),
        "initial_results": initial_results,
        "final_results": final_results,
        "analysis": state.get("analysis", {}),
        "pr_url": state.get("pr_url", ""),
        "pr_status": state.get("pr_status", ""),
        "pr_error": state.get("pr_error"),
    }


@rt.function_node
async def optimization_pipeline(
    repo_url: str, github_token: str, optimization_bias: str = "balanced", fast_mode: bool = False,
    selected_node_ids: list[str] | None = None, graph_data_json: str | None = None,
) -> dict:
    """Main orchestration flow — replaces the LangGraph StateGraph.

    Each stage calls the existing node functions directly (their signatures
    and internals are unchanged).  The retry loop and conditional routing
    that was previously expressed as graph edges is now a plain Python
    for-loop with break.

    When selected_node_ids and graph_data_json are provided (from the preview
    flowchart step), triage is replaced with deterministic node-based
    chunking that targets only the user-selected functions.
    """
    use_node_chunking = bool(selected_node_ids and graph_data_json)

    state: AgentState = {
        "repo_url": repo_url,
        "github_token": github_token,
        "optimization_bias": optimization_bias,
        "fast_mode": fast_mode,
        "selected_node_ids": selected_node_ids,
        "preview_graph_data": json.loads(graph_data_json) if graph_data_json else None,
        "messages": [],
    }

    # ── Clone ────────────────────────────────────────────────────────────
    await rt.broadcast("Cloning repository...")
    log.info("clone_start", repo_url=repo_url)
    repo_path = await clone_repo(repo_url, github_token)
    log.info("clone_complete", repo_path=repo_path)
    state["repo_path"] = repo_path
    state["messages"].append("Repository cloned successfully")

    # ── Parse AST ────────────────────────────────────────────────────────
    await rt.broadcast("Parsing codebase AST...")
    state.update(await parse_ast_node(state))

    # ── Triage / Node-based chunking ───────────────────────────────────
    if use_node_chunking:
        await rt.broadcast("Building optimization targets from selected nodes...")
        state.update(node_based_chunking(state))
    else:
        await rt.broadcast("Triaging codebase for hotspots...")
        state.update(await triage_node(state))

    # ── Streaming analysis + benchmarks ──────────────────────────────────
    # Each chunk independently: analyze -> gen benchmarks -> run benchmarks
    # Results include initial_results from the streaming pipeline
    await rt.broadcast("Streaming analysis and benchmarks per chunk...")
    state.update(await chunk_analyze_node(state))

    # ── Parallel: visualize + optimize + generate benchmark summaries ────────
    await rt.broadcast("Generating visualization, optimizations, and benchmark summaries...")
    viz_task = visualize_node(state)
    opt_task = optimize_node(state)
    bench_task = _generate_initial_benchmark_details(state)
    viz_result, opt_result, bench_result = await asyncio.gather(viz_task, opt_task, bench_task)

    base_msgs = list(state.get("messages", []))
    base_count = len(base_msgs)
    new_opt_msgs = opt_result.get("messages", [])[base_count:]

    state["optimized_files"] = opt_result.get("optimized_files", {})
    state["benchmark_details"] = bench_result.get("benchmark_details", [])
    state["graph_data"] = viz_result.get("graph_data", {})
    state["messages"] = base_msgs + new_opt_msgs

    # ── Optimization retry loop ──────────────────────────────────────────
    # Replaces LangGraph's conditional edges:
    #   rerun_benchmarks ─┬─▶ optimize  (if retry needed)
    #                     └─▶ report    (if done)
    for attempt in range(1, MAX_OPTIMIZATION_RETRIES + 2):
        await rt.broadcast(f"Re-running benchmarks (attempt {attempt})...")
        rerun_update = await _rerun_benchmarks(state)
        state.update(rerun_update)

        should_stop, reason = _should_stop_retrying(state)
        log.info(
            "should_retry_decision",
            decision="report" if should_stop else "optimize",
            reason=reason,
            retry_count=state.get("retry_count", 0),
            correctness_failures=len(state.get("correctness_failures", [])),
        )

        if should_stop:
            if state.get("correctness_failures"):
                state["optimized_files"] = _revert_broken_files(state)
            break

        await rt.broadcast("Re-optimizing based on benchmark feedback...")
        state.update(await optimize_node(state))

    # ── Report ───────────────────────────────────────────────────────────
    await rt.broadcast("Generating CodeMark report...")
    state.update(await report_node(state))

    # ── Create PR ────────────────────────────────────────────────────────
    await rt.broadcast("Creating pull request...")
    state.update(await _create_pr(state))

    # ── Cleanup ──────────────────────────────────────────────────────────
    repo_path = state.get("repo_path", "")
    if repo_path:
        await asyncio.to_thread(cleanup_repo, repo_path)
        log.info("cleanup_complete", repo_path=repo_path)

    return _extract_result(state)


async def run_optimization_pipeline(
    repo_url: str,
    github_token: str,
    queue: asyncio.Queue | None = None,
    optimization_bias: str = "balanced",
    fast_mode: bool = False,
    selected_node_ids: list[str] | None = None,
    graph_data: dict | None = None,
) -> dict:
    """Public entry point — creates a per-request Railtracks Flow and runs it.

    The signature is intentionally identical to the old LangGraph version so
    that ``main.py`` requires zero changes.
    """
    log.info(
        "pipeline_start",
        repo_url=repo_url,
        optimization_bias=optimization_bias,
        node_based=bool(selected_node_ids and graph_data),
    )
    pipeline_start = time.monotonic()

    # Serialize graph_data dict to JSON string for the railtracks node
    # (railtracks rejects dict types in @rt.function_node parameters)
    graph_data_json = json.dumps(graph_data) if graph_data else None

    broadcast_cb = None  # type: ignore[assignment]
    if queue:

        async def broadcast_cb(msg: str) -> None:
            await queue.put(
                {
                    "event": "progress",
                    "data": json.dumps({"node": "pipeline", "message": msg}),
                }
            )

    flow = rt.Flow(
        "CodeMark Optimization",
        entry_point=optimization_pipeline,
        broadcast_callback=broadcast_cb,
        save_state=True,
        timeout=900.0,
    )

    result = await flow.ainvoke(repo_url, github_token, optimization_bias, fast_mode, selected_node_ids, graph_data_json)

    total_elapsed = time.monotonic() - pipeline_start
    log.info("pipeline_complete", total_time_s=round(total_elapsed, 1))

    return result


@rt.function_node
async def preview_pipeline(repo_url: str, github_token: str) -> dict:
    """Lightweight pipeline — clone, parse, triage, and generate a preview graph.

    No benchmarks, no optimization.  Returns only graph_data.
    """
    state: AgentState = {
        "repo_url": repo_url,
        "github_token": github_token,
        "messages": [],
    }

    # ── Clone ────────────────────────────────────────────────────────────
    await rt.broadcast("Cloning repository...")
    log.info("preview_clone_start", repo_url=repo_url)
    repo_path = await clone_repo(repo_url, github_token)
    log.info("preview_clone_complete", repo_path=repo_path)
    state["repo_path"] = repo_path
    state["messages"].append("Repository cloned successfully")

    # ── Parse AST ────────────────────────────────────────────────────────
    await rt.broadcast("Parsing codebase AST...")
    state.update(await parse_ast_node(state))
    log.info(
        "preview_parse_complete",
        functions=len(state.get("ast_map", {}).get("functions", [])),
        files=len(state.get("file_tree", [])),
    )

    # ── Triage ───────────────────────────────────────────────────────────
    await rt.broadcast("Triaging codebase for hotspots...")
    state.update(await triage_node(state))
    log.info("preview_triage_complete")

    # ── Preview visualisation ────────────────────────────────────────────
    await rt.broadcast("Generating preview graph...")
    viz_result = await visualize_preview_node(state)
    state.update(viz_result)
    log.info(
        "preview_visualize_complete",
        nodes=len(state.get("graph_data", {}).get("nodes", [])),
        edges=len(state.get("graph_data", {}).get("edges", [])),
    )

    # ── Save graph to JSON file ──────────────────────────────────────────
    graph_data = state.get("graph_data", {})
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(output_dir, exist_ok=True)
    graph_output_path = os.path.join(output_dir, "preview_graph.json")
    with open(graph_output_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
    log.info("preview_graph_saved", path=graph_output_path)

    # ── Cleanup ──────────────────────────────────────────────────────────
    if repo_path:
        await asyncio.to_thread(cleanup_repo, repo_path)
        log.info("preview_cleanup_complete", repo_path=repo_path)

    return {"graph_data": graph_data}


async def run_preview_pipeline(
    repo_url: str,
    github_token: str,
    queue: asyncio.Queue | None = None,
) -> dict:
    """Public entry point for the preview (graph-only) pipeline."""
    log.info("preview_pipeline_start", repo_url=repo_url)
    pipeline_start = time.monotonic()

    broadcast_cb = None  # type: ignore[assignment]
    if queue:

        async def broadcast_cb(msg: str) -> None:
            await queue.put(
                {
                    "event": "progress",
                    "data": json.dumps({"node": "pipeline", "message": msg}),
                }
            )

    flow = rt.Flow(
        "CodeMark Preview",
        entry_point=preview_pipeline,
        broadcast_callback=broadcast_cb,
        save_state=True,
        timeout=300.0,
    )

    result = await flow.ainvoke(repo_url, github_token)

    total_elapsed = time.monotonic() - pipeline_start
    log.info("preview_pipeline_complete", total_time_s=round(total_elapsed, 1))

    return result


async def _run_local_pipeline(
    files: dict[str, str],
    language: str,
    optimization_bias: str = "balanced",
    fast_mode: bool = False,
    broadcast: object = None,
) -> dict:
    """Pipeline variant for local files — no git clone, no PR creation."""
    import shutil
    import tempfile

    async def _broadcast(msg: str) -> None:
        if broadcast and callable(broadcast):
            await broadcast(msg)

    state: AgentState = {
        "repo_url": "",
        "github_token": "",  # Not used for local
        "optimization_bias": optimization_bias,
        "fast_mode": fast_mode,
        "messages": [],
    }

    # Write files to a temp directory so existing nodes work unchanged
    temp_dir = tempfile.mkdtemp(prefix="codemark_local_")
    for rel_path, content in files.items():
        full_path = os.path.join(temp_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    state["repo_path"] = temp_dir
    state["messages"].append("Local files loaded")

    # ── Parse AST ────────────────────────────────────────────────────────
    await _broadcast("Parsing codebase AST...")
    state.update(await parse_ast_node(state))

    # ── Triage ───────────────────────────────────────────────────────────
    await _broadcast("Triaging codebase for hotspots...")
    state.update(await triage_node(state))

    # ── Streaming analysis + benchmarks ──────────────────────────────────
    await _broadcast("Streaming analysis and benchmarks per chunk...")
    state.update(await chunk_analyze_node(state))

    # ── Optimize ─────────────────────────────────────────────────────────
    await _broadcast("Generating optimizations...")
    opt_result = await optimize_node(state)
    state["optimized_files"] = opt_result.get("optimized_files", {})
    state["messages"] = opt_result.get("messages", state["messages"])

    # ── Optimization retry loop ──────────────────────────────────────────
    for attempt in range(1, MAX_OPTIMIZATION_RETRIES + 2):
        await _broadcast(f"Re-running benchmarks (attempt {attempt})...")
        rerun_update = await _rerun_benchmarks(state)
        state.update(rerun_update)

        should_stop, reason = _should_stop_retrying(state)
        log.info(
            "should_retry_decision",
            decision="report" if should_stop else "optimize",
            reason=reason,
            retry_count=state.get("retry_count", 0),
        )

        if should_stop:
            if state.get("correctness_failures"):
                state["optimized_files"] = _revert_broken_files(state)
            break

        await _broadcast("Re-optimizing based on benchmark feedback...")
        state.update(await optimize_node(state))

    # ── Report ───────────────────────────────────────────────────────────
    await _broadcast("Generating CodeMark report...")
    state.update(await report_node(state))

    # ── Cleanup ──────────────────────────────────────────────────────────
    shutil.rmtree(temp_dir, ignore_errors=True)

    return _extract_result(state)


async def run_local_optimization_pipeline(
    files: dict[str, str],
    language: str,
    queue: asyncio.Queue | None = None,
    optimization_bias: str = "balanced",
    fast_mode: bool = False,
) -> dict:
    """Public entry point for local file analysis."""
    log.info(
        "local_pipeline_start",
        num_files=len(files),
        language=language,
        optimization_bias=optimization_bias,
    )
    pipeline_start = time.monotonic()

    broadcast_cb = None
    if queue:

        async def broadcast_cb(msg: str) -> None:
            await queue.put(
                {
                    "event": "progress",
                    "data": json.dumps({"node": "pipeline", "message": msg}),
                }
            )

    result = await _run_local_pipeline(
        files, language, optimization_bias, fast_mode, broadcast=broadcast_cb
    )

    total_elapsed = time.monotonic() - pipeline_start
    log.info("local_pipeline_complete", total_time_s=round(total_elapsed, 1))

    return result
