import asyncio
import re
import traceback

import modal

BENCHMARK_TIMEOUT = 30
DEP_INSTALL_TIMEOUT = 45
FUNCTION_TIMEOUT = BENCHMARK_TIMEOUT + DEP_INSTALL_TIMEOUT + 15  # headroom

app = modal.App("codemark-benchmarks")

python_image = modal.Image.debian_slim(python_version="3.12").pip_install(
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

node_image = (
    modal.Image.debian_slim()
    .apt_install("curl")
    .run_commands(
        "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash",
        'bash -c "source /root/.nvm/nvm.sh && nvm install --lts && nvm use --lts"',
    )
    .run_commands(
        "bash -c 'ln -sf /root/.nvm/versions/node/*/bin/node /usr/local/bin/node && ln -sf /root/.nvm/versions/node/*/bin/npm /usr/local/bin/npm && ln -sf /root/.nvm/versions/node/*/bin/npx /usr/local/bin/npx'"
    )
    .run_commands(
        "npm install -g "
        "lodash@latest express@latest react@latest react-dom@latest next@latest "
        "axios@latest framer-motion@latest zod@latest "
        "typescript@latest ts-node@latest "
        "jest@latest mocha@latest chai@latest "
        "mongoose@latest pg@latest knex@latest sequelize@latest prisma@latest "
        "socket.io@latest ws@latest "
        "jsonwebtoken@latest bcrypt@latest uuid@latest "
        "dayjs@latest moment@latest date-fns@latest "
        "cheerio@latest node-fetch@latest "
        "@tanstack/react-query@latest swr@latest "
        "dotenv@latest mathjs@latest cors@latest helmet@latest "
        "morgan@latest body-parser@latest cookie-parser@latest"
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
    code = re.sub(r"export\s+default\s+", "module.exports = ", code)
    # export { X }  →  (just remove, not needed for benchmarks)
    code = re.sub(r"export\s*\{[^}]*\};?", "", code)
    return code


def _extract_local_module_names(repo_files: dict[str, str]) -> set[str]:
    """Build a set of top-level Python module names from the repo file paths.

    For a file like ``advanced_demo/server.py`` this yields ``advanced_demo``.
    For a root-level ``database.py`` this yields ``database``.
    Directories containing ``__init__.py`` are included as packages.
    """
    import os

    modules: set[str] = set()
    for path in repo_files:
        if not path.endswith(".py"):
            continue
        parts = path.replace("\\", "/").split("/")
        if len(parts) == 1:
            # Root-level file: ``database.py`` -> ``database``
            modules.add(os.path.splitext(parts[0])[0])
        else:
            # Nested file: top-level directory is the importable package name
            modules.add(parts[0])
    return modules


def _write_repo_files(workdir: str, repo_files: dict[str, str]) -> None:
    """Write repo file contents into the working directory.

    Also ensures every sub-directory that contains Python files has an
    ``__init__.py`` so it is treated as a package and sibling imports work.
    """
    import os

    for path, content in repo_files.items():
        full = os.path.join(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    # Ensure __init__.py exists in every directory that contains .py files
    # so that Python treats them as packages (required for relative imports).
    py_dirs: set[str] = set()
    for path in repo_files:
        if path.endswith(".py"):
            parent = os.path.dirname(os.path.join(workdir, path))
            if parent and parent != workdir:
                py_dirs.add(parent)
    for d in py_dirs:
        init_path = os.path.join(d, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("")


@app.function(image=python_image, timeout=FUNCTION_TIMEOUT)
def _run_python_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)

    # Install repo dependencies if requirements.txt exists
    req_txt = os.path.join(workdir, "requirements.txt")
    if os.path.exists(req_txt):
        subprocess.run(
            ["pip", "install", "-q", "-r", req_txt],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=DEP_INSTALL_TIMEOUT,
        )

    with open(os.path.join(workdir, "_benchmark_inner.py"), "w") as f:
        f.write(code)

    with open(os.path.join(workdir, "_benchmark.py"), "w") as f:
        f.write(PYTHON_MEMORY_WRAPPER)

    # Explicitly set PYTHONPATH to the workdir *and* every sub-directory that
    # contains Python files so that sibling imports resolve correctly.
    # e.g. advanced_demo/server.py can ``import database`` when database.py
    # sits next to it in advanced_demo/.
    env = os.environ.copy()
    py_dirs: set[str] = {workdir}
    for path in repo_files:
        if path.endswith(".py"):
            parent = os.path.dirname(os.path.join(workdir, path))
            if parent and parent != workdir:
                py_dirs.add(parent)
    env["PYTHONPATH"] = os.pathsep.join(sorted(py_dirs)) + os.pathsep + env.get("PYTHONPATH", "")

    local_modules = _extract_local_module_names(repo_files)

    for attempt in range(3):
        result = subprocess.run(
            ["python", os.path.join(workdir, "_benchmark.py")],
            capture_output=True,
            text=True,
            timeout=BENCHMARK_TIMEOUT,
            cwd=workdir,
            env=env,
        )
        if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
            m = re.search(
                r"ModuleNotFoundError: No module named '([^']+)'", result.stderr
            )
            if m:
                # Extract the top-level module name (e.g. "database" from "database.utils")
                missing_pkg = m.group(1).split(".")[0]
                if missing_pkg in local_modules:
                    # Local module — pip install won't help.  Fail fast.
                    import sys
                    print(
                        f"Local module '{missing_pkg}' failed to resolve. "
                        f"Check sys.path. (local_modules={sorted(local_modules)})",
                        file=sys.stderr,
                    )
                    break

                # External module — try to pip install and retry
                pkg_map = {
                    "PIL": "pillow",
                    "yaml": "pyyaml",
                    "bs4": "beautifulsoup4",
                    "dotenv": "python-dotenv",
                    "cv2": "opencv-python",
                }
                install_pkg = pkg_map.get(missing_pkg, missing_pkg)
                subprocess.run(
                    ["pip", "install", install_pkg], cwd=workdir, capture_output=True
                )
                continue
        break

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": (
            None
            if result.returncode == 0
            else f"Exit code {result.returncode}: {result.stderr[-500:]}"
        ),
    }


@app.function(image=node_image, timeout=FUNCTION_TIMEOUT)
def _run_js_benchmark(code: str, repo_files: dict[str, str]) -> dict:
    import subprocess
    import tempfile
    import os

    workdir = tempfile.mkdtemp()
    _write_repo_files(workdir, repo_files)

    # Install repo dependencies if package.json exists
    pkg_json = os.path.join(workdir, "package.json")
    if os.path.exists(pkg_json):
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=DEP_INSTALL_TIMEOUT,
        )

    with open(os.path.join(workdir, "_benchmark_inner.js"), "w") as f:
        f.write(_esm_to_cjs(code))

    with open(os.path.join(workdir, "_benchmark.js"), "w") as f:
        f.write(JS_MEMORY_WRAPPER)

    # Build set of local JS module basenames for fast-fail detection
    local_js_modules: set[str] = set()
    for path in repo_files:
        if path.endswith((".js", ".ts", ".jsx", ".tsx")):
            parts = path.replace("\\", "/").split("/")
            if len(parts) == 1:
                local_js_modules.add(os.path.splitext(parts[0])[0])
            else:
                local_js_modules.add(parts[0])

    for attempt in range(3):
        result = subprocess.run(
            ["node", os.path.join(workdir, "_benchmark.js")],
            capture_output=True,
            text=True,
            timeout=BENCHMARK_TIMEOUT,
            cwd=workdir,
        )
        if result.returncode != 0 and "Cannot find module" in result.stderr:
            m = re.search(r"Cannot find module '([^']+)'", result.stderr)
            if m:
                missing_pkg = m.group(1)
                # Relative imports (starting with .) are local — fail fast
                if missing_pkg.startswith("."):
                    import sys
                    print(
                        f"Local module '{missing_pkg}' failed to resolve. "
                        f"Check file paths in sandbox.",
                        file=sys.stderr,
                    )
                    break

                # extract root package name, ignoring subpaths like 'lodash/merge'
                root_pkg = missing_pkg.split("/")[0]
                if missing_pkg.startswith("@"):
                    parts = missing_pkg.split("/")
                    if len(parts) >= 2:
                        root_pkg = f"{parts[0]}/{parts[1]}"

                # Check if this is a local JS module — fail fast
                if root_pkg in local_js_modules:
                    import sys
                    print(
                        f"Local module '{root_pkg}' failed to resolve. "
                        f"Check file paths in sandbox. (local_modules={sorted(local_js_modules)})",
                        file=sys.stderr,
                    )
                    break

                subprocess.run(
                    [
                        "npm",
                        "install",
                        "--no-audit",
                        "--no-fund",
                        "--loglevel=error",
                        root_pkg,
                    ],
                    cwd=workdir,
                    capture_output=True,
                )
                continue
        break

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": (
            None
            if result.returncode == 0
            else f"Exit code {result.returncode}: {result.stderr[-500:]}"
        ),
    }


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

    repo_file_list = (
        "\n".join(f"  {p} ({len(c)} chars)" for p, c in files.items())
        if files
        else "  (none)"
    )

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
