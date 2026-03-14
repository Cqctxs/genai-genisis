import json

import structlog

from agent.schemas import GraphData
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

log = structlog.get_logger()

VISUALIZER_PROMPT = """You are a code visualization expert. Given an AST map (functions, classes,
call edges) and benchmark results (timing/memory per function), produce a semantic React Flow
graph that clearly communicates program execution flow and bottlenecks.

## Node Classification

Classify every node into exactly one node_type:

- "api"       — Functions that make HTTP requests (fetch, axios, requests, httpx, aiohttp, etc.)
- "llm"       — Functions that call an LLM / AI model (openai, anthropic, genai, pydantic_ai, langchain, etc.)
- "db"        — Functions that perform database operations (SQL queries, ORM calls, Redis, Mongo, etc.)
- "condition" — Branching logic: if/else, match/case, try/except guard, or any decision point
- "function"  — All other functions (general computation, utilities, orchestration)

## Node Data

For every node, populate:
- label: A short human-readable name (e.g. "Fetch User Profile", "Query Orders Table")
- file: The source file path
- node_type: One of the five types above
- inputs: Key-value pairs of the function's parameters (param_name → type or brief description).
           Omit if the function takes no meaningful args.
- outputs: Key-value pairs describing return values (key → brief description).
           Omit if the function returns nothing meaningful.
- metadata: Extra context depending on node_type:
    * api    → {"method": "GET/POST/…", "endpoint": "/path/or/url"}
    * llm    → {"model": "model-name", "purpose": "what the call does"}
    * db     → {"table": "table_name", "operation": "SELECT/INSERT/UPDATE/DELETE"}
    * condition → {"condition": "brief description of the branching logic"}
    * function  → {} or omit
- severity: Based on benchmark timing — "critical" (>1000ms), "high" (>500ms), "medium" (>100ms), "low" (<100ms)
- avg_time_ms, memory_mb: From benchmark results when available

## Edge Rules

- edge_type "call": A normal function call from source to target
- edge_type "branch_true" / "branch_false": Outgoing edges from a "condition" node.
  Label them with the branch description (e.g. "cache hit", "cache miss")
- edge_type "loop_back": When you detect a loop (for/while) or recursion, create an edge
  pointing BACKWARDS from a downstream node to the loop's entry point. Label it with
  the loop description (e.g. "for each item", "retry until success", "recurse on children")

## Layout Rules

- Arrange nodes in a readable top-to-bottom flow
- Space nodes ~200px apart vertically and ~300px apart horizontally
- Place condition nodes so their branches fan out left/right before merging back
- Loop-back edges will be rendered as curved backward arrows by the frontend

The output must be valid GraphData with nodes and edges arrays."""


async def visualize_node(state: AgentState) -> dict:
    """Transform AST map and benchmark results into React Flow graph data."""
    ast_map = state.get("ast_map", {})
    initial_results = state.get("initial_results", [])

    log.info(
        "visualize_start",
        ast_functions=len(ast_map.get("functions", [])),
        benchmark_results=len(initial_results),
    )

    agent = get_agent(GraphData, VISUALIZER_PROMPT, GEMINI_FLASH)

    prompt = f"""## AST Map
```json
{json.dumps(ast_map, indent=2)[:6000]}
```

## Benchmark Results
```json
{json.dumps(initial_results, indent=2)}
```

Analyze the AST to classify each function by node_type, extract inputs/outputs from
function signatures, populate metadata, and detect any loops or recursive calls.
Generate the semantic React Flow graph data."""

    result = await run_agent_logged(agent, prompt, node_name="visualize")
    graph_data: GraphData = result.output  # type: ignore[assignment]

    severity_counts = {}
    for node in graph_data.nodes:
        sev = node.severity or "none"
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    log.info(
        "visualize_complete",
        nodes=len(graph_data.nodes),
        edges=len(graph_data.edges),
        severity_breakdown=severity_counts,
    )

    return {
        **state,
        "graph_data": graph_data.model_dump(),
        "messages": state.get("messages", []) + [
            f"Generated visualization with {len(graph_data.nodes)} nodes and {len(graph_data.edges)} edges"
        ],
    }
