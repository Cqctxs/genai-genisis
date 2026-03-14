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
from agent.nodes.visualizer import visualize_node
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
    repo_url: str, github_token: str, optimization_bias: str = "balanced"
) -> dict:
    """Main orchestration flow — replaces the LangGraph StateGraph.

    Each stage calls the existing node functions directly (their signatures
    and internals are unchanged).  The retry loop and conditional routing
    that was previously expressed as graph edges is now a plain Python
    for-loop with break.
    """
    state: AgentState = {
        "repo_url": repo_url,
        "github_token": github_token,
        "optimization_bias": optimization_bias,
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

    # ── Triage ───────────────────────────────────────────────────────────
    await rt.broadcast("Triaging codebase for hotspots...")
    state.update(await triage_node(state))

    # ── Streaming analysis + benchmarks ──────────────────────────────────
    # Each chunk independently: analyze -> gen benchmarks -> run benchmarks
    # Results include initial_results from the streaming pipeline
    await rt.broadcast("Streaming analysis and benchmarks per chunk...")
    state.update(await chunk_analyze_node(state))

    # ── Parallel: visualize + optimize ───────────────────────────────────
    await rt.broadcast("Generating visualization and optimizations...")
    viz_task = visualize_node(state)
    opt_task = optimize_node(state)
    viz_result, opt_result = await asyncio.gather(viz_task, opt_task)

    base_msgs = list(state.get("messages", []))
    base_count = len(base_msgs)
    new_viz_msgs = viz_result.get("messages", [])[base_count:]
    new_opt_msgs = opt_result.get("messages", [])[base_count:]

    state["graph_data"] = viz_result.get("graph_data", {})
    state["optimized_files"] = opt_result.get("optimized_files", {})
    state["messages"] = base_msgs + new_viz_msgs + new_opt_msgs

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
) -> dict:
    """Public entry point — creates a per-request Railtracks Flow and runs it.

    The signature is intentionally identical to the old LangGraph version so
    that ``main.py`` requires zero changes.
    """
    log.info("pipeline_start", repo_url=repo_url, optimization_bias=optimization_bias)
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

    flow = rt.Flow(
        "CodeMark Optimization",
        entry_point=optimization_pipeline,
        broadcast_callback=broadcast_cb,
        save_state=True,
        timeout=900.0,
    )

    result = await flow.ainvoke(repo_url, github_token, optimization_bias)

    total_elapsed = time.monotonic() - pipeline_start
    log.info("pipeline_complete", total_time_s=round(total_elapsed, 1))

    return result


async def _run_local_pipeline(
    files: dict[str, str],
    language: str,
    optimization_bias: str = "balanced",
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
        "github_token": "",
        "optimization_bias": optimization_bias,
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
        files, language, optimization_bias, broadcast=broadcast_cb
    )

    total_elapsed = time.monotonic() - pipeline_start
    log.info("local_pipeline_complete", total_time_s=round(total_elapsed, 1))

    return result
