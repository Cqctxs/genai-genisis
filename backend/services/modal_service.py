import asyncio
import re
import traceback

import modal

BENCHMARK_TIMEOUT = 120
DEP_INSTALL_TIMEOUT = 120
FUNCTION_TIMEOUT = BENCHMARK_TIMEOUT + DEP_INSTALL_TIMEOUT + 30  # headroom
BATCH_FUNCTION_TIMEOUT = DEP_INSTALL_TIMEOUT + 8 * BENCHMARK_TIMEOUT + 60

app = modal.App("codemark-benchmarks")

python_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pyinstrument",
        "memory_profiler",
        "numpy",
        "pandas",
        "requests",
        "aiohttp",
        "pydantic",
        "sqlalchemy",
        "fastapi",
        "flask",
        "django",
        "celery",
        "redis",
        "httpx",
        "beautifulsoup4",
        "lxml",
        "pillow",
        "scipy",
        "scikit-learn",
        "pytest",
    )
)

node_image = (
    modal.Image.debian_slim()
    .apt_install("nodejs", "npm")
    .run_commands(
        "npm install -g "
        "lodash express react react-dom next "
        "axios framer-motion zod "
        "typescript ts-node "
        "jest mocha chai "
        "mongoose pg knex sequelize prisma "
        "socket.io ws "
        "jsonwebtoken bcrypt uuid "
        "dayjs moment date-fns "
        "cheerio node-fetch "
        "@tanstack/react-query swr"
    )
    .env({"NODE_PATH": "/usr/local/lib/node_modules"})
)

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


def _symlink_repo_into(repo_dir: str, bench_dir: str) -> None:
    """Symlink top-level repo entries into a per-benchmark subdirectory."""
    import os

    for entry in os.listdir(repo_dir):
        src = os.path.join(repo_dir, entry)
        dst = os.path.join(bench_dir, entry)
        if not os.path.lexists(dst):
            os.symlink(src, dst, target_is_directory=os.path.isdir(src))


def _install_python_deps(repo_dir: str) -> str:
    """pip install from requirements.txt if present. Returns a log string."""
    import os
    import subprocess

    req_path = os.path.join(repo_dir, "requirements.txt")
    if not os.path.isfile(req_path):
        return ""
    try:
        proc = subprocess.run(
            ["pip", "install", "-r", req_path, "--quiet", "--no-warn-script-location"],
            capture_output=True,
            text=True,
            timeout=DEP_INSTALL_TIMEOUT,
        )
        if proc.returncode != 0:
            return f"pip install failed (exit {proc.returncode}): {proc.stderr[-500:]}"
        return "pip install ok"
    except subprocess.TimeoutExpired:
        return f"pip install timed out after {DEP_INSTALL_TIMEOUT}s"
    except Exception as e:
        return f"pip install error: {e}"


def _install_js_deps(repo_dir: str) -> str:
    """npm install from package.json if present. Returns a log string."""
    import os
    import subprocess

    pkg_path = os.path.join(repo_dir, "package.json")
    if not os.path.isfile(pkg_path):
        return ""
    try:
        proc = subprocess.run(
            ["npm", "install", "--production", "--no-audit", "--no-fund"],
            capture_output=True,
            text=True,
            timeout=DEP_INSTALL_TIMEOUT,
            cwd=repo_dir,
        )
        if proc.returncode != 0:
            return f"npm install failed (exit {proc.returncode}): {proc.stderr[-500:]}"
        return "npm install ok"
    except subprocess.TimeoutExpired:
        return f"npm install timed out after {DEP_INSTALL_TIMEOUT}s"
    except Exception as e:
        return f"npm install error: {e}"


@app.function(image=python_image, timeout=FUNCTION_TIMEOUT)
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
        timeout=BENCHMARK_TIMEOUT,
        cwd=workdir,
    )

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {result.stderr[-500:]}",
    }


@app.function(image=node_image, timeout=FUNCTION_TIMEOUT)
def _run_js_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)

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

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if result.returncode == 0 else f"Exit code {result.returncode}: {result.stderr[-500:]}",
    }


# ---------------------------------------------------------------------------
# Batched benchmark execution
#
# These run all same-language benchmarks in a single container, writing repo
# files once, installing repo dependencies once, then looping over each
# benchmark in an isolated subdirectory (symlinked to shared repo files).
# ---------------------------------------------------------------------------


@app.function(image=python_image, timeout=BATCH_FUNCTION_TIMEOUT, min_containers=1)
def _run_python_benchmarks_batch(
    benchmarks: list[dict], repo_files: dict[str, str]
) -> list[dict]:
    """Run multiple Python benchmarks sequentially in a single container."""
    import os
    import subprocess
    import tempfile

    workdir = tempfile.mkdtemp()
    repo_dir = os.path.join(workdir, "_repo")
    os.makedirs(repo_dir)
    _write_repo_files(repo_dir, repo_files)

    _install_python_deps(repo_dir)

    results: list[dict] = []
    for bench in benchmarks:
        bid = bench["id"]
        bench_dir = os.path.join(workdir, f"_bench_{bid}")
        os.makedirs(bench_dir)
        _symlink_repo_into(repo_dir, bench_dir)

        with open(os.path.join(bench_dir, "_benchmark_inner.py"), "w") as f:
            f.write(bench["code"])
        with open(os.path.join(bench_dir, "_benchmark.py"), "w") as f:
            f.write(PYTHON_MEMORY_WRAPPER)

        try:
            proc = subprocess.run(
                ["python", "_benchmark.py"],
                capture_output=True,
                text=True,
                timeout=BENCHMARK_TIMEOUT,
                cwd=bench_dir,
            )
            results.append({
                "id": bid,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "error": (
                    None
                    if proc.returncode == 0
                    else f"Exit code {proc.returncode}: {proc.stderr[-500:]}"
                ),
            })
        except subprocess.TimeoutExpired:
            results.append({
                "id": bid,
                "stdout": "",
                "stderr": f"Benchmark timed out after {BENCHMARK_TIMEOUT}s",
                "error": f"Benchmark timed out after {BENCHMARK_TIMEOUT}s",
            })
        except Exception as e:
            results.append({
                "id": bid,
                "stdout": "",
                "stderr": str(e),
                "error": str(e),
            })

    return results


@app.function(image=node_image, timeout=BATCH_FUNCTION_TIMEOUT, min_containers=1)
def _run_js_benchmarks_batch(
    benchmarks: list[dict], repo_files: dict[str, str]
) -> list[dict]:
    """Run multiple JS benchmarks sequentially in a single container."""
    import os
    import subprocess
    import tempfile

    workdir = tempfile.mkdtemp()
    repo_dir = os.path.join(workdir, "_repo")
    os.makedirs(repo_dir)
    _write_repo_files(repo_dir, repo_files)

    _install_js_deps(repo_dir)

    results: list[dict] = []
    for bench in benchmarks:
        bid = bench["id"]
        bench_dir = os.path.join(workdir, f"_bench_{bid}")
        os.makedirs(bench_dir)
        _symlink_repo_into(repo_dir, bench_dir)

        with open(os.path.join(bench_dir, "_benchmark_inner.js"), "w") as f:
            f.write(_esm_to_cjs(bench["code"]))
        with open(os.path.join(bench_dir, "_benchmark.js"), "w") as f:
            f.write(JS_MEMORY_WRAPPER)

        try:
            proc = subprocess.run(
                ["node", "_benchmark.js"],
                capture_output=True,
                text=True,
                timeout=BENCHMARK_TIMEOUT,
                cwd=bench_dir,
            )
            results.append({
                "id": bid,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "error": (
                    None
                    if proc.returncode == 0
                    else f"Exit code {proc.returncode}: {proc.stderr[-500:]}"
                ),
            })
        except subprocess.TimeoutExpired:
            results.append({
                "id": bid,
                "stdout": "",
                "stderr": f"Benchmark timed out after {BENCHMARK_TIMEOUT}s",
                "error": f"Benchmark timed out after {BENCHMARK_TIMEOUT}s",
            })
        except Exception as e:
            results.append({
                "id": bid,
                "stdout": "",
                "stderr": str(e),
                "error": str(e),
            })

    return results


@app.function(image=python_image, timeout=30)
def _get_sandbox_specs() -> dict:
    """Collect hardware info from inside the Modal container."""
    import os
    import platform
    import subprocess

    cpu_info = {"model": "unknown", "cores": os.cpu_count() or 0}
    try:
        lscpu = subprocess.check_output(["lscpu"], text=True)
        for line in lscpu.splitlines():
            if line.startswith("Model name:"):
                cpu_info["model"] = line.split(":", 1)[1].strip()
            elif line.startswith("CPU(s):"):
                cpu_info["cores"] = int(line.split(":", 1)[1].strip())
    except Exception:
        pass

    try:
        ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3), 1)  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        ram_gb = 0.0

    return {
        "cpu_model": cpu_info["model"],
        "cpu_cores": cpu_info["cores"],
        "ram_gb": ram_gb,
        "python_version": platform.python_version(),
        "os": platform.platform(),
        "arch": platform.machine(),
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


async def run_benchmarks_batch(
    benchmarks: list[dict],
    repo_files: dict[str, str],
) -> list[dict]:
    """Execute benchmarks in batched Modal calls -- one per language.

    Each dict in *benchmarks* must have keys: id, code, language.
    Returns a list of dicts with keys: id, stdout, stderr, error -- in
    the same order as the input.
    """
    import time

    import structlog

    from services.log_utils import log_block

    log = structlog.get_logger()

    python_benchmarks = [b for b in benchmarks if b["language"] == "python"]
    js_benchmarks = [b for b in benchmarks if b["language"] != "python"]

    log_block(
        "MODAL BATCH CALL",
        metadata={
            "total_benchmarks": len(benchmarks),
            "python_count": len(python_benchmarks),
            "js_count": len(js_benchmarks),
            "repo_files_count": len(repo_files),
        },
        color="magenta",
    )

    start = time.monotonic()
    coros = []

    if python_benchmarks:
        fn = _lookup_function("_run_python_benchmarks_batch")
        coros.append(asyncio.to_thread(fn.remote, python_benchmarks, repo_files))
    if js_benchmarks:
        fn = _lookup_function("_run_js_benchmarks_batch")
        coros.append(asyncio.to_thread(fn.remote, js_benchmarks, repo_files))

    results_by_id: dict[int, dict] = {}

    try:
        raw_results = await asyncio.gather(*coros)
        for batch_results in raw_results:
            for r in batch_results:
                results_by_id[r["id"]] = r
    except Exception as e:
        elapsed = time.monotonic() - start
        log_block(
            "MODAL BATCH ERROR",
            metadata={
                "error_type": type(e).__name__,
                "elapsed_s": round(elapsed, 2),
            },
            sections={"ERROR": str(e), "TRACEBACK": traceback.format_exc()},
            color="red",
        )
        return [
            {"id": b["id"], "stdout": "", "stderr": str(e), "error": str(e)}
            for b in benchmarks
        ]

    elapsed = time.monotonic() - start
    ordered: list[dict] = []
    for b in benchmarks:
        r = results_by_id.get(
            b["id"],
            {
                "id": b["id"],
                "stdout": "",
                "stderr": "Missing from batch results",
                "error": "Missing from batch results",
            },
        )
        ordered.append(r)

    error_count = sum(1 for r in ordered if r.get("error"))
    log_block(
        "MODAL BATCH RESULT",
        metadata={
            "elapsed_s": round(elapsed, 2),
            "total_benchmarks": len(benchmarks),
            "errors": error_count,
        },
        sections={
            f"BENCH {r['id']}": (r.get("error") or "ok")
            for r in ordered
        },
        color="cyan" if error_count == 0 else "yellow",
    )

    return ordered


_specs_cache: dict | None = None


async def get_sandbox_specs() -> str:
    """Return a description of the Modal sandbox environment."""
    global _specs_cache
    if _specs_cache is None:
        try:
            fn = _lookup_function("_get_sandbox_specs")
            _specs_cache = await asyncio.to_thread(fn.remote)
        except Exception:
            return "Modal Cloud Container - Python 3.12, isolated execution"

    s = _specs_cache
    if s is None:
        return "Modal Cloud Container - Python 3.12, isolated execution"
    return (
        f"Modal Cloud Container\n"
        f"CPU: {s['cpu_model']} ({s['cpu_cores']} cores)\n"
        f"RAM: {s['ram_gb']} GB\n"
        f"Python: {s['python_version']}\n"
        f"OS: {s['os']} ({s['arch']})"
    )
