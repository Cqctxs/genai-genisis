import asyncio

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


async def run_benchmark(
    code: str,
    language: str,
    repo_files: dict[str, str] | None = None,
) -> dict:
    """Execute benchmark code in a Modal sandbox and return results."""
    import structlog
    log = structlog.get_logger()

    log.info("starting_modal_sandbox", language=language)
    files = repo_files or {}

    try:
        if language == "python":
            result = await asyncio.to_thread(
                _run_python_benchmark.remote, code, files
            )
        else:
            result = await asyncio.to_thread(
                _run_js_benchmark.remote, code, files
            )
    except Exception as e:
        log.error("modal_sandbox_failed", error=str(e))
        return {
            "stdout": "",
            "stderr": str(e),
            "error": str(e),
        }

    log.info("modal_sandbox_complete", has_error=result.get("error") is not None)
    return result


async def get_sandbox_specs() -> str:
    """Return a description of the Modal sandbox environment."""
    return "Modal Cloud Container - Python 3.12, isolated execution"
