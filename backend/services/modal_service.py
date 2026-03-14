import asyncio
import traceback

import modal

SANDBOX_TIMEOUT = 60

app = modal.App("codemark-benchmarks")

python_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "pyinstrument", "memory_profiler"
)

node_image = modal.Image.debian_slim().apt_install("nodejs", "npm")


@app.function(image=python_image, timeout=SANDBOX_TIMEOUT)
def _run_python_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    for path, content in repo_files.items():
        full = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    script_path = os.path.join(workdir, "_benchmark.py")
    with open(script_path, "w") as f:
        f.write(code)

    result = subprocess.run(
        ["python", script_path],
        capture_output=True,
        text=True,
        timeout=SANDBOX_TIMEOUT,
        cwd=workdir,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {result.stderr[-500:]}",
    }


@app.function(image=node_image, timeout=SANDBOX_TIMEOUT)
def _run_js_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    for path, content in repo_files.items():
        full = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    script_path = os.path.join(workdir, "_benchmark.js")
    with open(script_path, "w") as f:
        f.write(code)

    result = subprocess.run(
        ["node", script_path],
        capture_output=True,
        text=True,
        timeout=SANDBOX_TIMEOUT,
        cwd=workdir,
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {result.stderr[-500:]}",
    }


_fn_cache: dict[str, modal.Function] = {}


def _lookup_function(name: str) -> modal.Function:
    """Look up a deployed Modal function by name, with caching."""
    if name not in _fn_cache:
        _fn_cache[name] = modal.Function.from_name("codemark-benchmarks", name)
    return _fn_cache[name]


async def run_benchmark(
    code: str,
    language: str,
    repo_files: dict[str, str] | None = None,
) -> dict:
    """Execute benchmark code in a Modal sandbox and return results."""
    import structlog
    log = structlog.get_logger()

    files = repo_files or {}

    log.info(
        "modal_benchmark_start",
        language=language,
        script_chars=len(code),
        repo_files_count=len(files),
        script_preview=code[:200].replace("\n", "\\n"),
    )

    try:
        func_name = "_run_python_benchmark" if language == "python" else "_run_js_benchmark"
        fn = _lookup_function(func_name)
        log.info("modal_calling_remote", function=func_name)
        result = await asyncio.to_thread(fn.remote, code, files)
        log.info("modal_remote_returned", function=func_name)
    except Exception as e:
        log.error(
            "modal_sandbox_failed",
            language=language,
            error_type=type(e).__name__,
            error=str(e),
            traceback=traceback.format_exc(),
        )
        return {
            "stdout": "",
            "stderr": str(e),
            "error": str(e),
        }

    log.info(
        "modal_benchmark_result",
        language=language,
        has_error=result.get("error") is not None,
        stdout_chars=len(result.get("stdout", "")),
        stderr_chars=len(result.get("stderr", "")),
        stdout_preview=result.get("stdout", "")[:300].replace("\n", "\\n"),
        stderr_preview=result.get("stderr", "")[:300].replace("\n", "\\n") if result.get("stderr") else None,
        error=result.get("error"),
    )

    return result


async def get_sandbox_specs() -> str:
    """Return a description of the Modal sandbox environment."""
    return "Modal Cloud Container - Python 3.12, isolated execution"
