import asyncio
import json

import structlog
from langgraph.graph import END, StateGraph

from agent.nodes.analyzer import analyze_node, parse_ast_node
from agent.nodes.benchmarker import generate_benchmarks_node
from agent.nodes.optimizer import optimize_node
from agent.nodes.reporter import report_node
from agent.nodes.runner import run_benchmarks_node
from agent.nodes.visualizer import visualize_node
from agent.state import AgentState
from services.github_service import cleanup_repo, clone_repo

log = structlog.get_logger()

MAX_OPTIMIZATION_RETRIES = 2


async def clone_node(state: AgentState) -> AgentState:
    """Clone the repository."""
    repo_path = await clone_repo(state["repo_url"], state["github_token"])
    return {
        **state,
        "repo_path": repo_path,
        "messages": ["Repository cloned successfully"],
    }


async def rerun_benchmarks_node(state: AgentState) -> AgentState:
    """Re-run benchmarks on optimized code. Writes optimized files to repo first."""
    import os
    repo_path = state["repo_path"]
    optimized_files = state.get("optimized_files", {})

    for rel_path, content in optimized_files.items():
        full_path = os.path.join(repo_path, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    result = await run_benchmarks_node({**state, "initial_results": state.get("initial_results", [])})
    return {
        **state,
        "final_results": result.get("final_results", result.get("initial_results", [])),
        "messages": state.get("messages", []) + ["Re-ran benchmarks on optimized code"],
    }


def should_retry(state: AgentState) -> str:
    """Decide whether to retry optimization or finalize."""
    initial = state.get("initial_results", [])
    final = state.get("final_results", [])
    retry_count = state.get("_retry_count", 0)

    if retry_count >= MAX_OPTIMIZATION_RETRIES:
        return "report"

    if not initial or not final:
        return "report"

    initial_total = sum(r.get("avg_time_ms", 0) for r in initial)
    final_total = sum(r.get("avg_time_ms", 0) for r in final)

    if initial_total > 0 and final_total < initial_total:
        return "report"

    return "optimize"


async def cleanup_node(state: AgentState) -> AgentState:
    """Clean up cloned repo."""
    repo_path = state.get("repo_path", "")
    if repo_path:
        cleanup_repo(repo_path)
    return state


def build_graph() -> StateGraph:
    """Build the LangGraph optimization pipeline."""
    graph = StateGraph(AgentState)

    graph.add_node("clone", clone_node)
    graph.add_node("parse_ast", parse_ast_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate_benchmarks", generate_benchmarks_node)
    graph.add_node("run_benchmarks", run_benchmarks_node)
    graph.add_node("visualize", visualize_node)
    graph.add_node("optimize", optimize_node)
    graph.add_node("rerun_benchmarks", rerun_benchmarks_node)
    graph.add_node("report", report_node)
    graph.add_node("cleanup", cleanup_node)

    graph.set_entry_point("clone")
    graph.add_edge("clone", "parse_ast")
    graph.add_edge("parse_ast", "analyze")
    graph.add_edge("analyze", "generate_benchmarks")
    graph.add_edge("generate_benchmarks", "run_benchmarks")
    graph.add_edge("run_benchmarks", "visualize")
    graph.add_edge("visualize", "optimize")
    graph.add_edge("optimize", "rerun_benchmarks")
    graph.add_conditional_edges("rerun_benchmarks", should_retry, {
        "optimize": "optimize",
        "report": "report",
    })
    graph.add_edge("report", "cleanup")
    graph.add_edge("cleanup", END)

    return graph


compiled_graph = build_graph().compile()


async def run_optimization_pipeline(
    repo_url: str,
    github_token: str,
    queue: asyncio.Queue | None = None,
) -> dict:
    """Run the full optimization pipeline and stream updates."""
    initial_state: AgentState = {
        "repo_url": repo_url,
        "github_token": github_token,
        "messages": [],
    }

    final_state = {}
    async for event in compiled_graph.astream(initial_state):
        for node_name, state_update in event.items():
            log.info("node_completed", node=node_name)
            if queue and "messages" in state_update:
                for msg in state_update["messages"]:
                    await queue.put({
                        "event": "progress",
                        "data": json.dumps({"node": node_name, "message": msg}),
                    })
            final_state.update(state_update)

    result = {
        "graph_data": final_state.get("graph_data", {}),
        "comparison": final_state.get("comparison", {}),
        "optimized_files": final_state.get("optimized_files", {}),
        "initial_results": final_state.get("initial_results", []),
        "final_results": final_state.get("final_results", []),
        "analysis": final_state.get("analysis", {}),
    }

    return result
