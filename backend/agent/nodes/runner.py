import json
import traceback

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

    log.info(
        "run_benchmarks_start",
        num_benchmarks=len(benchmarks),
        results_key=results_key,
        targets=[b.target_function for b in benchmarks],
    )

    repo_files = {}
    for f in file_tree[:30]:
        try:
            repo_files[f] = read_file(repo_path, f)
        except Exception:
            pass

    log.info("run_benchmarks_repo_files_loaded", count=len(repo_files))

    results: list[dict] = []
    for i, bench in enumerate(benchmarks):
        log.info(
            "benchmark_executing",
            index=i,
            target=bench.target_function,
            file=bench.file,
            language=bench.language,
            script_chars=len(bench.script_content),
        )

        try:
            output = await run_benchmark(
                code=bench.script_content,
                language=bench.language,
                repo_files=repo_files,
            )

            if output.get("error"):
                log.error(
                    "benchmark_returned_error",
                    target=bench.target_function,
                    error=output["error"],
                    stdout=output.get("stdout", "")[:500],
                    stderr=output.get("stderr", "")[:500],
                )
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
            log.info(
                "benchmark_raw_output",
                target=bench.target_function,
                stdout=stdout[:500],
                stderr=output.get("stderr", "")[:200] if output.get("stderr") else None,
            )

            try:
                parsed = json.loads(stdout.strip().split("\n")[-1])
                bench_result = BenchmarkResult(
                    function_name=parsed.get("function", bench.target_function),
                    file=bench.file,
                    avg_time_ms=float(parsed.get("avg_time_ms", 0)),
                    memory_peak_mb=float(parsed.get("memory_peak_mb", 0)),
                    iterations=int(parsed.get("iterations", 0)),
                    raw_output=stdout,
                )
                log.info(
                    "benchmark_parsed",
                    target=bench_result.function_name,
                    avg_time_ms=bench_result.avg_time_ms,
                    memory_peak_mb=bench_result.memory_peak_mb,
                    iterations=bench_result.iterations,
                )
                results.append(bench_result.model_dump())
            except (json.JSONDecodeError, IndexError, ValueError) as parse_err:
                log.error(
                    "benchmark_parse_failed",
                    target=bench.target_function,
                    parse_error=str(parse_err),
                    stdout=stdout[:500],
                )
                results.append(BenchmarkResult(
                    function_name=bench.target_function,
                    file=bench.file,
                    avg_time_ms=0,
                    memory_peak_mb=0,
                    iterations=0,
                    raw_output=stdout,
                ).model_dump())

        except Exception as e:
            log.error(
                "benchmark_execution_crashed",
                target=bench.target_function,
                error_type=type(e).__name__,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            results.append(BenchmarkResult(
                function_name=bench.target_function,
                file=bench.file,
                avg_time_ms=0,
                memory_peak_mb=0,
                iterations=0,
                raw_output=str(e),
            ).model_dump())

    log.info(
        "run_benchmarks_complete",
        results_key=results_key,
        count=len(results),
        summary=[
            {"fn": r["function_name"], "time_ms": r["avg_time_ms"], "mem_mb": r["memory_peak_mb"]}
            for r in results
        ],
    )

    return {
        **state,
        results_key: results,
        "messages": state.get("messages", []) + [
            f"Completed {len(results)} benchmarks"
        ],
    }
