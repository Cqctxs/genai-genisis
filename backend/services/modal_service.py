import asyncio
import re
import traceback

import modal

BENCHMARK_TIMEOUT = 60
DEP_INSTALL_TIMEOUT = 120
FUNCTION_TIMEOUT = BENCHMARK_TIMEOUT + DEP_INSTALL_TIMEOUT + 30  # headroom

app = modal.App("codemark-benchmarks")

python_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "pyinstrument", "memory_profiler", "time", "json"
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


def _esm_to_cjs(code: str) -> str:
    """Convert ES module import/export statements to CommonJS equivalents.

    The JS memory wrapper loads the benchmark via require(), which means the
    inner script must be CommonJS.  Gemini frequently generates ESM syntax
    regardless of prompt instructions, so we patch it deterministically here.
    """
    # import { a, b } from "mod"  →  const { a, b } = require("mod")
    code = re.sub(
        r'import\s*\{([^}]+)\}\s*from\s*["\']([^"\']+)["\'];?',
        r'const {\1} = require("\2");',
        code,
    )
    # import X from "mod"  →  const X = require("mod")
    code = re.sub(
        r'import\s+(\w+)\s+from\s*["\']([^"\']+)["\'];?',
        r'const \1 = require("\2");',
        code,
    )
    # import "mod"  →  require("mod")
    code = re.sub(
        r'import\s+["\']([^"\']+)["\'];?',
        r'require("\1");',
        code,
    )
    # export default X  →  module.exports = X
    code = re.sub(r'export\s+default\s+', 'module.exports = ', code)
    # export { X }  →  (just remove, not needed for benchmarks)
    code = re.sub(r'export\s*\{[^}]*\};?', '', code)
    return code


def _write_repo_files(workdir: str, repo_files: dict[str, str]) -> None:
    """Write repo file contents into the working directory."""
    import os

    for path, content in repo_files.items():
        full = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


def _install_python_deps(workdir: str) -> str:
    """Install Python dependencies from requirements.txt. Returns install stderr."""
    import os
    import subprocess

    req_path = os.path.join(workdir, "requirements.txt")
    if not os.path.exists(req_path):
        return ""

    result = subprocess.run(
        ["pip", "install", "-r", req_path, "--quiet", "--no-cache-dir"],
        capture_output=True,
        text=True,
        timeout=DEP_INSTALL_TIMEOUT,
        cwd=workdir,
    )
    return result.stderr


def _install_js_deps(workdir: str) -> str:
    """Install Node.js dependencies from package.json. Returns install stderr."""
    import os
    import subprocess

    pkg_path = os.path.join(workdir, "package.json")
    if os.path.exists(pkg_path):
        result = subprocess.run(
            ["npm", "install", "--production", "--no-audit", "--no-fund"],
            capture_output=True,
            text=True,
            timeout=DEP_INSTALL_TIMEOUT,
            cwd=workdir,
        )
        return result.stderr

    return ""


@app.function(image=python_image, timeout=FUNCTION_TIMEOUT)
def _run_python_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)
    dep_stderr = _install_python_deps(workdir)

    with open(os.path.join(workdir, "_benchmark_inner.py"), "w") as f:
        f.write(code)

    with open(os.path.join(workdir, "_benchmark.py"), "w") as f:
        f.write(PYTHON_MEMORY_WRAPPER)

    result = subprocess.run(
        ["python", os.path.join(workdir, "_benchmark.py")],
        capture_output=True,
        text=True,
        timeout=BENCHMARK_TIMEOUT,
        cwd=workdir,
    )

    stderr = result.stderr
    if dep_stderr and result.returncode != 0:
        stderr = f"[pip install output]\n{dep_stderr}\n\n[benchmark stderr]\n{stderr}"

    return {
        "stdout": result.stdout,
        "stderr": stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {stderr[-500:]}",
    }


@app.function(image=node_image, timeout=FUNCTION_TIMEOUT)
def _run_js_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)
    dep_stderr = _install_js_deps(workdir)

    with open(os.path.join(workdir, "_benchmark_inner.js"), "w") as f:
        f.write(_esm_to_cjs(code))

    with open(os.path.join(workdir, "_benchmark.js"), "w") as f:
        f.write(JS_MEMORY_WRAPPER)

    result = subprocess.run(
        ["node", os.path.join(workdir, "_benchmark.js")],
        capture_output=True,
        text=True,
        timeout=BENCHMARK_TIMEOUT,
        cwd=workdir,
    )

    stderr = result.stderr
    if dep_stderr and result.returncode != 0:
        stderr = f"[npm install output]\n{dep_stderr}\n\n[benchmark stderr]\n{stderr}"

    return {
        "stdout": result.stdout,
        "stderr": stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {stderr[-500:]}",
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
    import time

    import structlog

    from services.log_utils import log_block

    log = structlog.get_logger()

    files = repo_files or {}
    func_name = "_run_python_benchmark" if language == "python" else "_run_js_benchmark"

    repo_file_list = "\n".join(f"  {p} ({len(c)} chars)" for p, c in files.items()) if files else "  (none)"

    log_block(
        f"MODAL CALL [{language}]",
        metadata={
            "function": func_name,
            "language": language,
            "script_chars": len(code),
            "repo_files_count": len(files),
        },
        sections={
            "BENCHMARK SCRIPT": code,
            "REPO FILES": repo_file_list,
        },
        color="magenta",
    )

    start = time.monotonic()
    try:
        fn = _lookup_function(func_name)
        result = await asyncio.to_thread(fn.remote, code, files)
    except Exception as e:
        elapsed = time.monotonic() - start
        log_block(
            f"MODAL ERROR [{language}]",
            metadata={
                "function": func_name,
                "error_type": type(e).__name__,
                "elapsed_s": round(elapsed, 2),
            },
            sections={"ERROR": str(e), "TRACEBACK": traceback.format_exc()},
            color="red",
        )
        return {
            "stdout": "",
            "stderr": str(e),
            "error": str(e),
        }

    elapsed = time.monotonic() - start
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    error = result.get("error")

    sections: dict[str, str] = {"STDOUT": stdout if stdout else "(empty)"}
    if stderr:
        sections["STDERR"] = stderr
    if error:
        sections["ERROR"] = error

    log_block(
        f"MODAL RESULT [{language}]",
        metadata={
            "function": func_name,
            "elapsed_s": round(elapsed, 2),
            "has_error": error is not None,
            "stdout_chars": len(stdout),
            "stderr_chars": len(stderr),
        },
        sections=sections,
        color="cyan" if not error else "yellow",
    )

    return result


async def get_sandbox_specs() -> str:
    """Return a description of the Modal sandbox environment."""
    return "Modal Cloud Container - Python 3.12, isolated execution"
