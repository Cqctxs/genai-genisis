import json

import structlog

from agent.schemas import GraphData
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent

log = structlog.get_logger()

VISUALIZER_PROMPT = """You are a code visualization expert. Given an AST map (functions, classes,
call edges) and benchmark results (timing/memory per function), produce a React Flow graph.

Rules:
- Each function that was benchmarked should be a node
- Include important related functions as nodes too (callers/callees from the AST)
- Edges represent call relationships from the AST call_edges
- Node positions should form a readable top-to-bottom or left-to-right layout
- Space nodes ~200px apart vertically and ~300px apart horizontally
- Set severity based on benchmark timing: "critical" (>1000ms), "high" (>500ms), "medium" (>100ms), "low" (<100ms)
- Include avg_time_ms and memory_mb from benchmark results on each node

The output must be valid GraphData with nodes and edges arrays."""


async def visualize_node(state: AgentState) -> dict:
    """Transform AST map and benchmark results into React Flow graph data."""
    ast_map = state.get("ast_map", {})
    initial_results = state.get("initial_results", [])

    agent = get_agent(GraphData, VISUALIZER_PROMPT, GEMINI_PRO)

    prompt = f"""## AST Map
```json
{json.dumps(ast_map, indent=2)[:6000]}
```

## Benchmark Results
```json
{json.dumps(initial_results, indent=2)}
```

Generate the React Flow graph data."""

    log.info("generating_visualization")
    result = await agent.run(prompt)
    graph_data: GraphData = result.output  # type: ignore[assignment]

    return {
        **state,
        "graph_data": graph_data.model_dump(),
        "messages": state.get("messages", []) + [
            f"Generated visualization with {len(graph_data.nodes)} nodes and {len(graph_data.edges)} edges"
        ],
    }
