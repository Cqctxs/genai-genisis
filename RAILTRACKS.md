# Railtracks Integration

CodeMark uses [Railtracks](https://www.railtown.ai/) by Railtown as the orchestration framework for its AI agent workflow. Railtracks manages the end-to-end optimization pipeline, handling flow execution, real-time progress broadcasting, and state persistence.

## Why Railtracks

The pipeline was originally designed around LangGraph's `StateGraph` with conditional edges and the `Send` API for parallel execution. We migrated to Railtracks because it lets us express the same orchestration logic as plain Python control flow — `for` loops, `if/else`, and `asyncio.gather` — while still providing managed execution, state persistence, and a built-in broadcast mechanism for real-time progress updates.

## Core API Usage

Railtracks is used exclusively in `backend/agent/graph.py`. The individual agent nodes (analyzer, benchmarker, optimizer, etc.) are plain async Python functions and do not depend on Railtracks directly.

### 1. `@rt.function_node` — Defining the Pipeline

The main orchestration function is decorated with `@rt.function_node`, which registers it as a trackable Railtracks node:

```python
import railtracks as rt

@rt.function_node
async def optimization_pipeline(
    repo_url: str, github_token: str, optimization_bias: str = "balanced", fast_mode: bool = False
) -> dict:
    """Main orchestration flow — replaces the LangGraph StateGraph."""
    ...
```

Inside this function, each pipeline stage calls existing node functions directly. Conditional routing and retry logic that was previously expressed as graph edges is now standard Python:

```python
# Retry loop replaces LangGraph conditional edges
for attempt in range(1, MAX_OPTIMIZATION_RETRIES + 2):
    await rt.broadcast(f"Re-running benchmarks (attempt {attempt})...")
    rerun_update = await _rerun_benchmarks(state)
    state.update(rerun_update)

    should_stop, reason = _should_stop_retrying(state)
    if should_stop:
        break

    await rt.broadcast("Re-optimizing based on benchmark feedback...")
    state.update(await optimize_node(state))
```

Parallel execution uses `asyncio.gather` instead of LangGraph's `Send`:

```python
viz_task = visualize_node(state)
opt_task = optimize_node(state)
bench_task = _generate_initial_benchmark_details(state)
viz_result, opt_result, bench_result = await asyncio.gather(viz_task, opt_task, bench_task)
```

### 2. `rt.broadcast()` — Real-Time Progress Updates

`rt.broadcast` sends progress messages from inside the pipeline to any registered callback. We use this to push Server-Sent Events (SSE) to the frontend so users see live status updates:

```python
await rt.broadcast("Cloning repository...")
await rt.broadcast("Parsing codebase AST...")
await rt.broadcast("Triaging codebase for hotspots...")
await rt.broadcast("Streaming analysis and benchmarks per chunk...")
await rt.broadcast("Generating visualization, optimizations, and benchmark summaries...")
await rt.broadcast("Generating CodeMark report...")
await rt.broadcast("Creating pull request...")
```

The broadcast callback is wired up when the Flow is created. It pushes messages into an `asyncio.Queue` that the FastAPI SSE endpoint consumes:

```python
async def broadcast_cb(msg: str) -> None:
    await queue.put({
        "event": "progress",
        "data": json.dumps({"node": "pipeline", "message": msg}),
    })
```

### 3. `rt.Flow` — Managed Execution

Each incoming request creates a new `rt.Flow` instance that wraps the pipeline with execution management:

```python
flow = rt.Flow(
    "CodeMark Optimization",
    entry_point=optimization_pipeline,
    broadcast_callback=broadcast_cb,
    save_state=True,
    timeout=900.0,
)

result = await flow.ainvoke(repo_url, github_token, optimization_bias, fast_mode)
```

| Parameter            | Value                   | Purpose                                                   |
| -------------------- | ----------------------- | --------------------------------------------------------- |
| `entry_point`        | `optimization_pipeline` | The `@rt.function_node` function to execute               |
| `broadcast_callback` | `broadcast_cb`          | Receives `rt.broadcast` messages for SSE streaming        |
| `save_state`         | `True`                  | Persists flow state to the local `.railtracks/` directory |
| `timeout`            | `900.0`                 | 15-minute timeout for the entire pipeline run             |

## Pipeline Stages

The full agent workflow orchestrated by Railtracks:

```
Clone Repository
       |
Parse AST (Tree-sitter)
       |
Triage hotspots (Gemini Flash)
       |
Streaming chunk analysis + benchmarks (parallel per-chunk)
       |
   +---+---+------------------------+
   |       |                        |
Visualize  Optimize (Gemini Pro)   Benchmark summaries
   |       |                        |
   +---+---+------------------------+
       |
Optimization retry loop (up to 2 retries)
   |-- Re-run benchmarks on optimized code
   |-- Check improvement + correctness
   |-- Re-optimize if regression detected
       |
Generate CodeMark report
       |
Create GitHub PR
       |
Cleanup
```

## Local State

Railtracks persists flow state to a `.railtracks/` directory in the project root when `save_state=True`. This directory is gitignored and should not be committed.

## Dependencies

```
railtracks>=1.2.0
```

Listed in `backend/requirements.txt`. Installed automatically with `pip install -r requirements.txt`.
