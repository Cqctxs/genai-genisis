import asyncio
import json
import traceback

import structlog

from agent.schemas import BenchmarkResult, BenchmarkScript, slim_ast_for_prompt
from agent.state import AgentState
from services.modal_service import run_benchmark
from services.github_service import read_file

log = structlog.get_logger()

MAX_BENCH_RETRIES = 2


SUSPECT_TIME_THRESHOLD_MS = 0.001


def _is_failed_result(result: dict) -> bool:
    """A benchmark result counts as failed if it produced no usable timing data.

    Catches three cases:
    1. Script crashed (both time and iterations are 0)
    2. Script ran but reported 0ms with iterations > 0 (dead code elimination)
    3. Script reported a sub-microsecond time that's below measurement resolution
    """
    avg_time = result.get("avg_time_ms", 0)
    iterations = result.get("iterations", 0)

    if avg_time == 0 and iterations == 0:
        return True

    if iterations > 0 and avg_time < SUSPECT_TIME_THRESHOLD_MS:
        log.warning(
            "benchmark_suspect_zero_time",
            function=result.get("function_name", "unknown"),
            avg_time_ms=avg_time,
            iterations=iterations,
        )
        return True

    return False


async def _regenerate_benchmark(
    bench: BenchmarkScript,
    error_msg: str,
    stderr: str,
    ast_map: dict,
    repo_files: dict[str, str],
) -> BenchmarkScript | None:
    """Ask Gemini to fix a benchmark script that failed at runtime."""
    from agent.nodes.benchmarker import BENCHMARK_PROMPT
    from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

    filtered_ast = slim_ast_for_prompt({
        "functions": [f for f in ast_map.get("functions", []) if f.get("file") == bench.file],
        "classes": [c for c in ast_map.get("classes", []) if c.get("file") == bench.file],
        "imports": [i for i in ast_map.get("imports", []) if i.get("file") == bench.file],
    })

    # Detect timeout errors and add specific guidance
    is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()
    timeout_guidance = ""
    if is_timeout:
        timeout_guidance = """
### CRITICAL: Execution Timeout Detected
The script took too long to run. The function has high algorithmic complexity.
**You MUST reduce the input size or number of iterations significantly:**
- Start with N=1000 or fewer (not 10,000+)
- Use 5-10 iterations only (not 50+)
- Prioritize completing in under 15 seconds total
- Smaller inputs reveal algorithmic differences better than slow large inputs
"""

    is_attribute_error = "AttributeError" in error_msg
    if is_attribute_error:
        timeout_guidance += """\n### CRITICAL: AttributeError from Mock Patch
If you used `unittest.mock.patch` without importing the module first, it will crash.
**You MUST `import module` before patching any of its attributes.** (e.g. if you patch `advanced_demo.main.os.path.exists`, you MUST do `import advanced_demo.main` before the patch). Or completely remove the use of `patch` and use manual stubbing.

Also, if a mock object is passed as an argument to a function that accesses `func.__name__`, the mock MUST have `__name__` explicitly set:
```python
mock_fn = MagicMock()
mock_fn.__name__ = 'original_function_name'
```
Prefer running the ACTUAL target function rather than mocking it. Only mock external I/O dependencies."""


    fix_prompt = f"""## Previous Benchmark Script FAILED at Runtime

The following benchmark script for `{bench.target_function}` crashed when executed
in the sandbox. Regenerate a FIXED version that avoids the error.
{timeout_guidance}

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

### Original File Content ({bench.file})
```{bench.language}
{repo_files.get(bench.file, "(File content not found)")[:15000]}
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
        agent = get_agent(BenchmarkScript, BENCHMARK_PROMPT, GEMINI_FLASH)
        result = await run_agent_logged(
            agent, fix_prompt, node_name=f"fix_bench_{bench.target_function}"
        )
        fixed: BenchmarkScript = result.output  # type: ignore[assignment]
        log.info(
            "benchmark_regenerated",
            target=fixed.target_function,
            file=fixed.file,
            script_chars=len(fixed.script_content),
        )
        return fixed
    except Exception as e:
        log.error(
            "benchmark_regeneration_failed", target=bench.target_function, error=str(e)
        )
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
        log.error(
            "benchmark_empty_stdout", target=bench.target_function, stderr=stderr[:500]
        )
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
    allow_regeneration: bool = True,
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
        if remaining <= 0 or ast_map is None or not allow_regeneration:
            if remaining <= 0:
                log.warning(
                    "benchmark_max_retries_exhausted", target=bench.target_function
                )
            elif not allow_regeneration:
                log.warning(
                    "benchmark_regeneration_disabled", target=bench.target_function
                )
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
            repo_files,
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
    """Execute benchmark scripts in Modal sandboxes in parallel and collect results.

    On re-runs, benchmarks whose target file was not modified by the optimizer are
    short-circuited: the previous result is reused and no Modal call is made.
    """
    benchmarks = [BenchmarkScript(**b) for b in state.get("benchmark_code", [])]
    repo_path = state.get("repo_path", "")
    file_tree = state.get("file_tree", [])
    results_key = (
        "initial_results" if "initial_results" not in state else "final_results"
    )

    # Build a lookup from (function_name, file) -> previous result so unmodified
    # benchmarks can be reused cheaply.  On the initial run there are no previous
    # results, so this dict is empty and every benchmark runs normally.
    optimized_files: set[str] = set(state.get("optimized_files", {}).keys())
    previous_results: list[dict] = state.get(
        "final_results", state.get("initial_results", [])
    )
    prev_by_key: dict[tuple[str, str], dict] = {
        (r.get("function_name", ""), r.get("file", "")): r for r in previous_results
    }

    log.info(
        "run_benchmarks_start",
        num_benchmarks=len(benchmarks),
        results_key=results_key,
        optimized_files=list(optimized_files),
        targets=[b.target_function for b in benchmarks],
    )

    repo_files = {}
    for f in file_tree:
        try:
            repo_files[f] = read_file(repo_path, f)
        except Exception:
            pass

    # Apply optimized files so the final benchmark actually measures the new code
    for opt_file, opt_content in state.get("optimized_files", {}).items():
        repo_files[opt_file] = opt_content

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

    async def _run_or_reuse(bench: BenchmarkScript, index: int) -> dict:
        key = (bench.target_function, bench.file)

        # If the original baseline completely failed, do not rerun it, just return the failure
        initial_res = next(
            (
                r
                for r in state.get("initial_results", [])
                if r.get("function_name") == bench.target_function
                and r.get("file") == bench.file
            ),
            None,
        )
        if initial_res and _is_failed_result(initial_res):
            log.warning(
                "benchmark_skipping_previously_broken", target=bench.target_function
            )
            return initial_res

        # Only skip if we actually know which files were optimized (re-run) AND
        # this benchmark's file was not among them.
        if optimized_files and bench.file not in optimized_files:
            cached = prev_by_key.get(key)
            if cached is not None:
                log.info(
                    "benchmark_reused_unchanged_file",
                    target=bench.target_function,
                    file=bench.file,
                )
                return cached
        return await _execute_single_benchmark(
            bench, index, repo_files, ast_map=ast_map or None
        )

    tasks = [_run_or_reuse(bench, i) for i, bench in enumerate(benchmarks)]
    results = list(await asyncio.gather(*tasks))

    total_time = sum(r["avg_time_ms"] for r in results)
    log.info(
        "run_benchmarks_complete",
        results_key=results_key,
        count=len(results),
        total_time_ms=round(total_time, 1),
        summary=[
            {"fn": r["function_name"], "time_ms": r["avg_time_ms"]} for r in results[:5]
        ],
    )

    update: dict = {
        **state,
        results_key: results,
        "messages": state.get("messages", [])
        + [f"Completed {len(results)} benchmarks"],
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
            matched = sum(1 for r in results if r.get("validation_fingerprint"))
            log.info("correctness_check_passed", fingerprints_matched=matched)
            update["correctness_failures"] = []

    return update
