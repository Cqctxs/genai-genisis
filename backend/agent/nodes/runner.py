import asyncio
import json
import traceback

import structlog

from agent.schemas import BenchmarkResult, BenchmarkScript
from agent.state import AgentState
from services.modal_service import run_benchmark
from services.github_service import read_file

log = structlog.get_logger()

MAX_BENCH_RETRIES = 2


def _is_failed_result(result: dict) -> bool:
    """A benchmark result counts as failed if it produced no usable timing data."""
    return result.get("avg_time_ms", 0) == 0 and result.get("iterations", 0) == 0


async def _regenerate_benchmark(
    bench: BenchmarkScript,
    error_msg: str,
    stderr: str,
    ast_map: dict,
) -> BenchmarkScript | None:
    """Ask Gemini to fix a benchmark script that failed at runtime."""
    from agent.nodes.benchmarker import BENCHMARK_PROMPT
    from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged

    filtered_ast = {
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") == bench.file],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") == bench.file],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") == bench.file],
    }

    fix_prompt = f"""## Previous Benchmark Script FAILED at Runtime

The following benchmark script for `{bench.target_function}` crashed when executed
in the sandbox. Regenerate a FIXED version that avoids the error.

### Error
```
{error_msg[:1000]}
```

### Stderr
```
{stderr[:1000]}
```

### Original Script
```{bench.language}
{bench.script_content}
```

### AST Context (functions in the target file: {bench.file})
```json
{json.dumps(filtered_ast, indent=2)[:3000]}
```

IMPORTANT:
- The script runs in a sandbox with common packages pre-installed, but you should
  STILL prefer mocking over importing when the dependency isn't essential.
- Do NOT run `npm install`, `pip install`, or any package manager commands — this will crash the container.
- Ensure mock data shapes match exactly what the function expects.
- The language is: {bench.language}
- Do NOT reuse the broken mock data from the previous attempt."""

    try:
        agent = get_agent(BenchmarkScript, BENCHMARK_PROMPT, GEMINI_PRO)
        result = await run_agent_logged(agent, fix_prompt, node_name=f"fix_bench_{bench.target_function}")
        fixed: BenchmarkScript = result.output  # type: ignore[assignment]
        log.info(
            "benchmark_regenerated",
            target=fixed.target_function,
            file=fixed.file,
            script_chars=len(fixed.script_content),
        )
        return fixed
    except Exception as e:
        log.error("benchmark_regeneration_failed", target=bench.target_function, error=str(e))
        return None


def _parse_benchmark_output(
    bench: BenchmarkScript, output: dict
) -> tuple[dict, str | None]:
    """Parse sandbox output into a BenchmarkResult dict.

    Returns (result_dict, error_description). error_description is None on success.
    """
    if output.get("error"):
        return (
            BenchmarkResult(
                function_name=bench.target_function,
                file=bench.file,
                avg_time_ms=0,
                memory_peak_mb=0,
                iterations=0,
                raw_output=output.get("stderr", ""),
            ).model_dump(),
            output["error"],
        )

    stdout = output.get("stdout", "")
    stderr = output.get("stderr", "")
    log.info(
        "benchmark_raw_output",
        target=bench.target_function,
        stdout=stdout[:500],
        stderr=stderr[:500] if stderr else None,
    )

    if not stdout.strip():
        log.error("benchmark_empty_stdout", target=bench.target_function, stderr=stderr[:500])
        return (
            BenchmarkResult(
                function_name=bench.target_function,
                file=bench.file,
                avg_time_ms=0,
                memory_peak_mb=0,
                iterations=0,
                raw_output=stderr or "No output from benchmark",
            ).model_dump(),
            f"Empty stdout. stderr: {stderr[:500]}",
        )

    try:
        parsed = json.loads(stdout.strip().split("\n")[-1])
        fingerprint = parsed.get("validation_fingerprint")
        bench_result = BenchmarkResult(
            function_name=parsed.get("function", bench.target_function),
            file=bench.file,
            avg_time_ms=float(parsed.get("avg_time_ms", 0)),
            memory_peak_mb=float(parsed.get("memory_peak_mb", 0)),
            iterations=int(parsed.get("iterations", 0)),
            raw_output=stdout,
            validation_fingerprint=fingerprint,
        )
        log.info(
            "benchmark_parsed",
            target=bench_result.function_name,
            avg_time_ms=bench_result.avg_time_ms,
            memory_peak_mb=bench_result.memory_peak_mb,
            iterations=bench_result.iterations,
            validation_fingerprint=fingerprint,
        )
        return bench_result.model_dump(), None
    except (json.JSONDecodeError, IndexError, ValueError) as parse_err:
        log.error(
            "benchmark_parse_failed",
            target=bench.target_function,
            parse_error=str(parse_err),
            stdout=stdout[:500],
        )
        return (
            BenchmarkResult(
                function_name=bench.target_function,
                file=bench.file,
                avg_time_ms=0,
                memory_peak_mb=0,
                iterations=0,
                raw_output=stdout,
            ).model_dump(),
            f"JSON parse error: {parse_err}. stdout: {stdout[:300]}",
        )


async def _execute_single_benchmark(
    bench: BenchmarkScript,
    index: int,
    repo_files: dict[str, str],
    ast_map: dict | None = None,
) -> dict:
    """Execute a single benchmark, retrying with Gemini regeneration on failure."""
    current_bench = bench

    for attempt in range(1 + MAX_BENCH_RETRIES):
        log.info(
            "benchmark_executing",
            index=index,
            attempt=attempt + 1,
            target=current_bench.target_function,
            file=current_bench.file,
            language=current_bench.language,
            script_chars=len(current_bench.script_content),
        )

        try:
            output = await run_benchmark(
                code=current_bench.script_content,
                language=current_bench.language,
                repo_files=repo_files,
            )
        except Exception as e:
            log.error(
                "benchmark_execution_crashed",
                target=current_bench.target_function,
                attempt=attempt + 1,
                error_type=type(e).__name__,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            output = {"stdout": "", "stderr": str(e), "error": str(e)}

        result, error_desc = _parse_benchmark_output(current_bench, output)

        if error_desc:
            log.error(
                "benchmark_returned_error",
                target=current_bench.target_function,
                attempt=attempt + 1,
                error=error_desc[:500],
                stderr=output.get("stderr", "")[:500],
            )

        if not _is_failed_result(result):
            return result

        remaining = MAX_BENCH_RETRIES - attempt
        if remaining <= 0 or ast_map is None:
            if remaining <= 0:
                log.warning("benchmark_max_retries_exhausted", target=bench.target_function)
            return result

        log.info(
            "benchmark_retry_regenerating",
            target=bench.target_function,
            attempt=attempt + 1,
            remaining=remaining,
        )
        fixed = await _regenerate_benchmark(
            current_bench,
            error_desc or "Unknown failure",
            output.get("stderr", ""),
            ast_map,
        )
        if fixed is None:
            return result
        current_bench = fixed

    return result


def compare_fingerprints(
    initial_results: list[dict],
    final_results: list[dict],
) -> list[dict]:
    """Compare validation fingerprints between initial and final benchmark runs.

    Returns a list of dicts describing each mismatch:
      {"function_name": ..., "file": ..., "initial_fp": ..., "final_fp": ...}
    """
    initial_map: dict[str, str | None] = {}
    for r in initial_results:
        key = r.get("function_name", "")
        fp = r.get("validation_fingerprint")
        if key and fp:
            initial_map[key] = fp

    failures: list[dict] = []
    for r in final_results:
        fn = r.get("function_name", "")
        final_fp = r.get("validation_fingerprint")
        initial_fp = initial_map.get(fn)

        if initial_fp is None or final_fp is None:
            continue

        if initial_fp != final_fp:
            failure = {
                "function_name": fn,
                "file": r.get("file", ""),
                "initial_fingerprint": initial_fp,
                "final_fingerprint": final_fp,
            }
            log.warning("correctness_mismatch", **failure)
            failures.append(failure)

    return failures


async def run_benchmarks_node(state: AgentState) -> dict:
    """Execute benchmark scripts in Modal sandboxes in parallel and collect results."""
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

    for manifest in ("requirements.txt", "package.json"):
        if manifest not in repo_files:
            try:
                repo_files[manifest] = read_file(repo_path, manifest)
            except Exception:
                pass

    log.info(
        "run_benchmarks_repo_files_loaded",
        count=len(repo_files),
        has_requirements_txt="requirements.txt" in repo_files,
        has_package_json="package.json" in repo_files,
    )

    ast_map = state.get("ast_map", {})

    tasks = [
        _execute_single_benchmark(bench, i, repo_files, ast_map=ast_map)
        for i, bench in enumerate(benchmarks)
    ]
    results = list(await asyncio.gather(*tasks))

    total_time = sum(r["avg_time_ms"] for r in results)
    log.info(
        "run_benchmarks_complete",
        results_key=results_key,
        count=len(results),
        total_time_ms=round(total_time, 1),
        summary=[
            {"fn": r["function_name"], "time_ms": r["avg_time_ms"]}
            for r in results[:5]
        ],
    )

    update: dict = {
        **state,
        results_key: results,
        "messages": state.get("messages", []) + [
            f"Completed {len(results)} benchmarks"
        ],
    }

    if results_key == "final_results":
        initial_results = state.get("initial_results", [])
        failures = compare_fingerprints(initial_results, results)
        if failures:
            failed_fns = [f["function_name"] for f in failures]
            log.warning(
                "correctness_failures_detected",
                count=len(failures),
                functions=failed_fns,
            )
            update["correctness_failures"] = failures
            update["messages"] = update["messages"] + [
                f"Correctness check: {len(failures)} function(s) changed behavior: {', '.join(failed_fns)}"
            ]
        else:
            matched = sum(
                1 for r in results if r.get("validation_fingerprint")
            )
            log.info("correctness_check_passed", fingerprints_matched=matched)
            update["correctness_failures"] = []

    return update
