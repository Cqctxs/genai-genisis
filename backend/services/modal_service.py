import asyncio
import traceback

import modal

SANDBOX_TIMEOUT = 60

app = modal.App("codemark-benchmarks")

python_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "pyinstrument", "memory_profiler"
)

node_image = modal.Image.debian_slim().apt_install("nodejs", "npm")

# ---------------------------------------------------------------------------
# Memory measurement wrappers
#
# These scripts wrap the user-generated benchmark script so that memory
# measurement is deterministic — no reliance on the LLM generating the
# right instrumentation code.
# ---------------------------------------------------------------------------

PYTHON_MEMORY_WRAPPER = """\
import sys as _sys
import io as _io
import json as _json
import tracemalloc as _tracemalloc
import runpy as _runpy

_tracemalloc.start()
_orig_stdout = _sys.stdout
_capture = _io.StringIO()
_sys.stdout = _capture

try:
    _runpy.run_path("_benchmark_inner.py", run_name="__main__")
except SystemExit:
    pass
finally:
    _sys.stdout = _orig_stdout

_, _peak_bytes = _tracemalloc.get_traced_memory()
_tracemalloc.stop()
_mem_mb = round(_peak_bytes / (1024 * 1024), 2)

_output = _capture.getvalue()
_lines = _output.rstrip("\\n").split("\\n") if _output.strip() else []

_patched = False
for _i in range(len(_lines) - 1, -1, -1):
    try:
        _obj = _json.loads(_lines[_i])
        if isinstance(_obj, dict):
            _obj["memory_peak_mb"] = _mem_mb
            _lines[_i] = _json.dumps(_obj)
            _patched = True
            break
    except (_json.JSONDecodeError, ValueError):
        continue

if _lines:
    print("\\n".join(_lines))

if not _patched:
    print(_json.dumps({"memory_peak_mb": _mem_mb}))
"""

JS_MEMORY_WRAPPER = """\
const _captured = [];
const _origLog = console.log;
console.log = (...args) => _captured.push(args.map(String).join(' '));

const _initialMem = process.memoryUsage().heapUsed;

try {
    require('./_benchmark_inner.js');
} catch (e) {
    console.log = _origLog;
    console.error(e.stack || e.message);
    process.exit(1);
}

const _peakMem = process.memoryUsage().heapUsed;
const _memMb = Math.round(Math.max(0, (_peakMem - _initialMem)) / (1024 * 1024) * 100) / 100;

console.log = _origLog;

let _patched = false;
for (let _i = _captured.length - 1; _i >= 0; _i--) {
    try {
        const _obj = JSON.parse(_captured[_i]);
        if (typeof _obj === 'object' && _obj !== null && !Array.isArray(_obj)) {
            _obj.memory_peak_mb = _memMb;
            _captured[_i] = JSON.stringify(_obj);
            _patched = true;
            break;
        }
    } catch (e) {}
}

_captured.forEach(line => console.log(line));

if (!_patched) {
    console.log(JSON.stringify({ memory_peak_mb: _memMb }));
}
"""


def _write_repo_files(workdir: str, repo_files: dict[str, str]) -> None:
    """Write repo file contents into the working directory."""
    import os

    for path, content in repo_files.items():
        full = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


@app.function(image=python_image, timeout=SANDBOX_TIMEOUT)
def _run_python_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)

    with open(os.path.join(workdir, "_benchmark_inner.py"), "w") as f:
        f.write(code)

    with open(os.path.join(workdir, "_benchmark.py"), "w") as f:
        f.write(PYTHON_MEMORY_WRAPPER)

    result = subprocess.run(
        ["python", os.path.join(workdir, "_benchmark.py")],
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
    _write_repo_files(workdir, repo_files)

    with open(os.path.join(workdir, "_benchmark_inner.js"), "w") as f:
        f.write(code)

    with open(os.path.join(workdir, "_benchmark.js"), "w") as f:
        f.write(JS_MEMORY_WRAPPER)

    result = subprocess.run(
        ["node", os.path.join(workdir, "_benchmark.js")],
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


def _lookup_function(name: str) -> modal.Function:
    """Look up a deployed Modal function by name."""
    return modal.Function.from_name("codemark-benchmarks", name)


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
