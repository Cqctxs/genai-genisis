import json

import structlog

from agent.schemas import BenchmarkResult, BenchmarkScript
from agent.state import AgentState
from services.modal_service import run_benchmark
from services.github_service import read_file

log = structlog.get_logger()


async def run_benchmarks_node(state: AgentState) -> dict:
    """Execute benchmark scripts in Modal sandboxes and collect results."""
    benchmarks = [BenchmarkScript(**b) for b in state.get("benchmark_code", [])]
    repo_path = state.get("repo_path", "")
    file_tree = state.get("file_tree", [])
    results_key = "initial_results" if "initial_results" not in state else "final_results"

    repo_files = {}
    for f in file_tree[:30]:
        try:
            repo_files[f] = read_file(repo_path, f)
        except Exception:
            pass

    results: list[dict] = []
    for bench in benchmarks:
        log.info("running_benchmark", target=bench.target_function, file=bench.file)
        try:
            output = await run_benchmark(
                code=bench.script_content,
                language=bench.language,
                repo_files=repo_files,
            )

            if output.get("error"):
                log.warning("benchmark_error", target=bench.target_function, error=output["error"])
                results.append(BenchmarkResult(
                    function_name=bench.target_function,
                    file=bench.file,
                    avg_time_ms=0,
                    memory_peak_mb=0,
                    iterations=0,
                    raw_output=output.get("stderr", ""),
                ).model_dump())
                continue

            stdout = output.get("stdout", "")
            try:
                parsed = json.loads(stdout.strip().split("\n")[-1])
                results.append(BenchmarkResult(
                    function_name=parsed.get("function", bench.target_function),
                    file=bench.file,
                    avg_time_ms=float(parsed.get("avg_time_ms", 0)),
                    memory_peak_mb=float(parsed.get("memory_peak_mb", 0)),
                    iterations=int(parsed.get("iterations", 0)),
                    raw_output=stdout,
                ).model_dump())
            except (json.JSONDecodeError, IndexError, ValueError):
                results.append(BenchmarkResult(
                    function_name=bench.target_function,
                    file=bench.file,
                    avg_time_ms=0,
                    memory_peak_mb=0,
                    iterations=0,
                    raw_output=stdout,
                ).model_dump())

        except Exception as e:
            log.error("benchmark_execution_failed", target=bench.target_function, error=str(e))
            results.append(BenchmarkResult(
                function_name=bench.target_function,
                file=bench.file,
                avg_time_ms=0,
                memory_peak_mb=0,
                iterations=0,
                raw_output=str(e),
            ).model_dump())

    return {
        **state,
        results_key: results,
        "messages": state.get("messages", []) + [
            f"Completed {len(results)} benchmarks"
        ],
    }
