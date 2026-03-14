import asyncio
import json
import time
import traceback

import structlog
from langgraph.graph import END, StateGraph

from agent.nodes.analyzer import parse_ast_node, triage_node, chunk_analyze_node
from agent.nodes.optimizer import optimize_node
from agent.nodes.reporter import report_node
from agent.nodes.runner import run_benchmarks_node
from agent.nodes.visualizer import visualize_node
from agent.state import AgentState
from services.github_pr_service import create_optimization_pr
from services.github_service import cleanup_repo, clone_repo

log = structlog.get_logger()

MAX_OPTIMIZATION_RETRIES = 1


async def clone_node(state: AgentState) -> dict:
    """Clone the repository."""
    repo_url = state.get("repo_url", "")
    log.info("clone_start", repo_url=repo_url)
    repo_path = await clone_repo(repo_url, state.get("github_token", ""))
    log.info("clone_complete", repo_path=repo_path)
    return {
        **state,
        "repo_path": repo_path,
        "messages": ["Repository cloned successfully"],
    }


async def visualize_and_optimize_node(state: AgentState) -> dict:
    """Run visualization and optimization in parallel after benchmarks."""
    log.info("visualize_and_optimize_start")

    viz_task = visualize_node(state)
    opt_task = optimize_node(state)

    viz_result, opt_result = await asyncio.gather(viz_task, opt_task)

    log.info("visualize_and_optimize_complete")

    base_msgs = state.get("messages", [])
    base_count = len(base_msgs)
    new_viz_msgs = viz_result.get("messages", [])[base_count:]
    new_opt_msgs = opt_result.get("messages", [])[base_count:]

    return {
        **state,
        "graph_data": viz_result.get("graph_data", {}),
        "optimized_files": opt_result.get("optimized_files", {}),
        "messages": base_msgs + new_viz_msgs + new_opt_msgs,
    }


async def rerun_benchmarks_node(state: AgentState) -> dict:
    """Re-run benchmarks on optimized code. Writes optimized files to repo first."""
    import os
    repo_path = state.get("repo_path", "")
    optimized_files = state.get("optimized_files", {})

    log.info("rerun_benchmarks_start", num_optimized_files=len(optimized_files))

    for rel_path, content in optimized_files.items():
        full_path = os.path.join(repo_path, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info("rerun_wrote_optimized_file", path=rel_path, chars=len(content))

    result = await run_benchmarks_node({**state, "initial_results": state.get("initial_results", [])})

    log.info("rerun_benchmarks_complete")

    return {
        **state,
        "final_results": result.get("final_results", result.get("initial_results", [])),
        "retry_count": state.get("retry_count", 0) + 1,
        "messages": state.get("messages", []) + ["Re-ran benchmarks on optimized code"],
    }


def should_retry(state: AgentState) -> str:
    """Decide whether to retry optimization or finalize."""
    initial = state.get("initial_results", [])
    final = state.get("final_results", [])
    retry_count = state.get("retry_count", 0)

    initial_total = sum(r.get("avg_time_ms", 0) for r in initial)
    final_total = sum(r.get("avg_time_ms", 0) for r in final)

    decision = "report"
    reason = ""

    if retry_count >= MAX_OPTIMIZATION_RETRIES:
        reason = f"max retries reached ({retry_count})"
    elif not initial or not final:
        reason = f"missing results (initial={len(initial)}, final={len(final)})"
    elif initial_total == 0 and final_total == 0:
        reason = "all benchmarks returned 0ms (likely sandbox failures), skipping retry"
    elif initial_total > 0 and final_total < initial_total:
        reason = f"improvement detected ({initial_total:.1f}ms -> {final_total:.1f}ms)"
    elif initial_total > 0 and abs(final_total - initial_total) / initial_total < 0.05:
        reason = f"marginal difference ({initial_total:.1f}ms -> {final_total:.1f}ms, <5%), not worth retrying"
    else:
        decision = "optimize"
        reason = f"no improvement ({initial_total:.1f}ms -> {final_total:.1f}ms), retrying"

    log.info(
        "should_retry_decision",
        decision=decision,
        reason=reason,
        retry_count=retry_count,
        initial_total_ms=initial_total,
        final_total_ms=final_total,
    )

    return decision


async def cleanup_node(state: AgentState) -> dict:
    """Clean up cloned repo."""
    repo_path = state.get("repo_path", "")
    if repo_path:
        await asyncio.to_thread(cleanup_repo, repo_path)
        log.info("cleanup_complete", repo_path=repo_path)
    return {}


async def create_pr_node(state: AgentState) -> dict:
    """Create a GitHub PR with the optimized code. Non-fatal on failure."""
    repo_url = state.get("repo_url", "")
    github_token = state.get("github_token", "")
    optimized_files = state.get("optimized_files", {})
    comparison = state.get("comparison", {})

    if not optimized_files:
        log.warning("create_pr_skipped", reason="no optimized files")
        return {**state, "pr_url": ""}

    try:
        pr_url = await create_optimization_pr(
            repo_url=repo_url,
            github_token=github_token,
            optimized_files=optimized_files,
            comparison=comparison,
        )
        log.info("create_pr_complete", pr_url=pr_url)
        return {
            **state,
            "pr_url": pr_url,
            "messages": state.get("messages", []) + [f"Pull request created: {pr_url}"],
        }
    except Exception as e:
        log.error("create_pr_failed", error=str(e), traceback=traceback.format_exc())
        return {
            **state,
            "pr_url": "",
            "messages": state.get("messages", []) + [f"PR creation failed: {e}"],
        }


def build_graph() -> StateGraph:
    """Build the LangGraph optimization pipeline."""
    graph = StateGraph(AgentState)

    graph.add_node("clone", clone_node)
    graph.add_node("parse_ast", parse_ast_node)
    graph.add_node("triage", triage_node)
    graph.add_node("chunk_analyze", chunk_analyze_node)
    graph.add_node("run_benchmarks", run_benchmarks_node)
    graph.add_node("visualize_and_optimize", visualize_and_optimize_node)
    graph.add_node("optimize", optimize_node)
    graph.add_node("rerun_benchmarks", rerun_benchmarks_node)
    graph.add_node("report", report_node)
    graph.add_node("create_pr", create_pr_node)
    graph.add_node("cleanup", cleanup_node)

    graph.set_entry_point("clone")
    graph.add_edge("clone", "parse_ast")
    graph.add_edge("parse_ast", "triage")
    graph.add_edge("triage", "chunk_analyze")
    graph.add_edge("chunk_analyze", "run_benchmarks")
    graph.add_edge("run_benchmarks", "visualize_and_optimize")
    graph.add_edge("visualize_and_optimize", "rerun_benchmarks")
    graph.add_conditional_edges("rerun_benchmarks", should_retry, {
        "optimize": "optimize",
        "report": "report",
    })
    graph.add_edge("optimize", "rerun_benchmarks")
    graph.add_edge("report", "create_pr")
    graph.add_edge("create_pr", "cleanup")
    graph.add_edge("cleanup", END)

    return graph


compiled_graph = build_graph().compile()


async def run_optimization_pipeline(
    repo_url: str,
    github_token: str,
    queue: asyncio.Queue | None = None,
) -> dict:
    """Run the full optimization pipeline and stream updates."""
    log.info("pipeline_start", repo_url=repo_url)
    pipeline_start = time.monotonic()

    initial_state: AgentState = {
        "repo_url": repo_url,
        "github_token": github_token,
        "messages": [],
    }

    final_state = {}
    sent_message_count = 0
    async for event in compiled_graph.astream(initial_state):
        for node_name, state_update in event.items():
            if not state_update:
                log.info("node_completed_empty", node=node_name)
                continue
            elapsed = time.monotonic() - pipeline_start
            state_keys = [k for k in state_update.keys() if k != "messages" and k != "github_token"]

            log.info(
                "node_completed",
                node=node_name,
                elapsed_s=round(elapsed, 1),
                state_keys=state_keys,
            )

            if queue and "messages" in state_update:
                new_messages = state_update["messages"][sent_message_count:]
                for msg in new_messages:
                    await queue.put({
                        "event": "progress",
                        "data": json.dumps({"node": node_name, "message": msg}),
                    })
                sent_message_count = len(state_update["messages"])
            final_state.update(state_update)

    total_elapsed = time.monotonic() - pipeline_start
    log.info("pipeline_complete", total_elapsed_s=round(total_elapsed, 1))

    result = {
        "graph_data": final_state.get("graph_data", {}),
        "comparison": final_state.get("comparison", {}),
        "optimized_files": final_state.get("optimized_files", {}),
        "initial_results": final_state.get("initial_results", []),
        "final_results": final_state.get("final_results", []),
        "analysis": final_state.get("analysis", {}),
        "pr_url": final_state.get("pr_url", ""),
    }

    return result
