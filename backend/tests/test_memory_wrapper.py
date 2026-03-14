"""Tests for the deterministic memory measurement wrappers.

Validates that the Python (tracemalloc) and JS (process.memoryUsage) wrappers
correctly inject memory_peak_mb into benchmark script output, regardless of
whether the LLM-generated script includes memory measurement code.
"""
import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Python wrapper — end-to-end (runs the actual wrapper via sys.executable)
# ---------------------------------------------------------------------------


class TestPythonWrapperEndToEnd:
    """Run the Python memory wrapper with real subprocess + tracemalloc."""

    def _run_wrapper(self, inner_code: str, repo_files: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        from services.modal_service import PYTHON_MEMORY_WRAPPER

        workdir = tempfile.mkdtemp()

        if repo_files:
            for path, content in repo_files.items():
                full = os.path.join(workdir, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write(content)

        with open(os.path.join(workdir, "_benchmark_inner.py"), "w") as f:
            f.write(inner_code)

        with open(os.path.join(workdir, "_benchmark.py"), "w") as f:
            f.write(PYTHON_MEMORY_WRAPPER)

        return subprocess.run(
            [sys.executable, os.path.join(workdir, "_benchmark.py")],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workdir,
        )

    def test_injects_memory_into_timing_only_json(self):
        """Script outputs timing JSON without memory → wrapper adds memory_peak_mb."""
        inner = (
            'import json, time\n'
            'start = time.perf_counter()\n'
            'data = [i**2 for i in range(10000)]\n'
            'elapsed = (time.perf_counter() - start) * 1000\n'
            'print(json.dumps({"function": "square_list", "avg_time_ms": round(elapsed, 3), "iterations": 1}))\n'
        )
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip().split("\n")[-1])
        assert "memory_peak_mb" in parsed
        assert parsed["memory_peak_mb"] > 0
        assert parsed["function"] == "square_list"
        assert "avg_time_ms" in parsed

    def test_overrides_existing_memory_field(self):
        """Script outputs JSON with memory_peak_mb=0 → wrapper overrides with real value."""
        inner = (
            'import json\n'
            'data = bytearray(1024 * 1024)\n'  # ~1 MB allocation
            'print(json.dumps({"function": "alloc", "avg_time_ms": 1.0, "memory_peak_mb": 0, "iterations": 1}))\n'
        )
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip().split("\n")[-1])
        assert parsed["memory_peak_mb"] > 0

    def test_preserves_multiline_output(self):
        """Debug output before JSON line is preserved."""
        inner = (
            'import json\n'
            'print("Loading data...")\n'
            'print("Processing...")\n'
            'print(json.dumps({"function": "test", "avg_time_ms": 5.0, "iterations": 10}))\n'
        )
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3
        assert lines[0] == "Loading data..."
        assert lines[1] == "Processing..."

        parsed = json.loads(lines[2])
        assert "memory_peak_mb" in parsed
        assert parsed["function"] == "test"

    def test_handles_no_json_output(self):
        """Script prints non-JSON → wrapper appends memory-only JSON."""
        inner = 'print("hello world")\n'
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        lines = result.stdout.strip().split("\n")
        assert lines[0] == "hello world"
        last = json.loads(lines[-1])
        assert "memory_peak_mb" in last

    def test_handles_empty_output(self):
        """Script produces no stdout → wrapper still outputs memory JSON."""
        inner = "x = 42\n"
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip())
        assert "memory_peak_mb" in parsed

    def test_script_error_propagates(self):
        """Script that raises should still result in non-zero exit code."""
        inner = 'raise ValueError("intentional failure")\n'
        result = self._run_wrapper(inner)
        assert result.returncode != 0
        assert "ValueError" in result.stderr

    def test_script_with_sys_exit_zero(self):
        """sys.exit(0) should be caught, memory is still reported."""
        inner = (
            'import json, sys\n'
            'print(json.dumps({"function": "early_exit", "avg_time_ms": 0.1, "iterations": 1}))\n'
            'sys.exit(0)\n'
        )
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip().split("\n")[-1])
        assert "memory_peak_mb" in parsed
        assert parsed["function"] == "early_exit"

    def test_repo_files_importable(self):
        """Repo files written to workdir are importable by the inner script."""
        repo_files = {"mylib.py": "VALUE = 42\n"}
        inner = (
            'import json, mylib\n'
            'print(json.dumps({"function": "import_test", "avg_time_ms": 0.0, "iterations": 1, "value": mylib.VALUE}))\n'
        )
        result = self._run_wrapper(inner, repo_files=repo_files)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip().split("\n")[-1])
        assert parsed["value"] == 42
        assert "memory_peak_mb" in parsed

    def test_significant_allocation_reflected(self):
        """Large allocation should produce a measurably non-trivial memory_peak_mb."""
        inner = (
            'import json\n'
            'big = bytearray(5 * 1024 * 1024)\n'  # 5 MB
            'print(json.dumps({"function": "big_alloc", "avg_time_ms": 0.0, "iterations": 1}))\n'
        )
        result = self._run_wrapper(inner)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        parsed = json.loads(result.stdout.strip().split("\n")[-1])
        assert parsed["memory_peak_mb"] >= 4.0, (
            f"Expected >= 4 MB for a 5 MB allocation, got {parsed['memory_peak_mb']}"
        )


# ---------------------------------------------------------------------------
# Python wrapper — unit tests for Modal function file setup
# ---------------------------------------------------------------------------


class TestPythonBenchmarkFileSetup:
    """Verify _run_python_benchmark writes the correct files."""

    def test_writes_inner_script_and_wrapper(self):
        from services.modal_service import _run_python_benchmark, PYTHON_MEMORY_WRAPPER

        written_files = {}

        def capture_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", "")
            for root, _, files in os.walk(cwd):
                for f in files:
                    fpath = os.path.join(root, f)
                    rel = os.path.relpath(fpath, cwd)
                    with open(fpath) as fh:
                        written_files[rel] = fh.read()
            return MagicMock(stdout="", stderr="", returncode=0)

        with patch("subprocess.run", side_effect=capture_run):
            _run_python_benchmark.local(code="print('hello')", repo_files={})

        assert "_benchmark_inner.py" in written_files
        assert written_files["_benchmark_inner.py"] == "print('hello')"
        assert "_benchmark.py" in written_files
        assert written_files["_benchmark.py"] == PYTHON_MEMORY_WRAPPER

    def test_subprocess_runs_wrapper_not_inner(self):
        from services.modal_service import _run_python_benchmark

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)) as mock_run:
            _run_python_benchmark.local(code="x = 1", repo_files={})

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "python"
        assert cmd[1].endswith("_benchmark.py")
        assert "_benchmark_inner" not in cmd[1]

    def test_repo_files_written_alongside_scripts(self):
        from services.modal_service import _run_python_benchmark

        written = []

        def capture_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", "")
            for root, _, files in os.walk(cwd):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), cwd)
                    written.append(rel.replace("\\", "/"))
            return MagicMock(stdout="", stderr="", returncode=0)

        repo_files = {"src/util.py": "pass\n", "lib/data.py": "x = 1\n"}
        with patch("subprocess.run", side_effect=capture_run):
            _run_python_benchmark.local(code="x", repo_files=repo_files)

        assert "_benchmark.py" in written
        assert "_benchmark_inner.py" in written
        assert "src/util.py" in written
        assert "lib/data.py" in written


# ---------------------------------------------------------------------------
# JS wrapper — unit tests for Modal function file setup
# ---------------------------------------------------------------------------


class TestJsBenchmarkFileSetup:
    """Verify _run_js_benchmark writes the correct files."""

    def test_writes_inner_script_and_wrapper(self):
        from services.modal_service import _run_js_benchmark, JS_MEMORY_WRAPPER

        written_files = {}

        def capture_run(cmd, **kwargs):
            cwd = kwargs.get("cwd", "")
            for root, _, files in os.walk(cwd):
                for f in files:
                    fpath = os.path.join(root, f)
                    rel = os.path.relpath(fpath, cwd)
                    with open(fpath) as fh:
                        written_files[rel] = fh.read()
            return MagicMock(stdout="", stderr="", returncode=0)

        with patch("subprocess.run", side_effect=capture_run):
            _run_js_benchmark.local(code="console.log('hi')", repo_files={})

        assert "_benchmark_inner.js" in written_files
        assert written_files["_benchmark_inner.js"] == "console.log('hi')"
        assert "_benchmark.js" in written_files
        assert written_files["_benchmark.js"] == JS_MEMORY_WRAPPER

    def test_subprocess_runs_wrapper_not_inner(self):
        from services.modal_service import _run_js_benchmark

        with patch("subprocess.run", return_value=MagicMock(stdout="", stderr="", returncode=0)) as mock_run:
            _run_js_benchmark.local(code="x = 1", repo_files={})

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "node"
        assert cmd[1].endswith("_benchmark.js")
        assert "_benchmark_inner" not in cmd[1]


# ---------------------------------------------------------------------------
# Integration: run_benchmark → runner parsing with memory data
# ---------------------------------------------------------------------------


class TestRunnerParsesWrappedOutput:
    """Verify run_benchmarks_node correctly parses memory_peak_mb from wrapped output."""

    def _make_state(self, **overrides):
        base = {
            "benchmark_code": [
                {
                    "target_function": "process_data",
                    "file": "app.py",
                    "language": "python",
                    "script_content": "print('hi')",
                    "description": "bench",
                }
            ],
            "repo_path": "/tmp/fake",
            "file_tree": [],
            "messages": [],
        }
        base.update(overrides)
        return base

    async def test_memory_peak_mb_parsed_from_output(self):
        from unittest.mock import AsyncMock
        from agent.nodes.runner import run_benchmarks_node

        modal_output = {
            "stdout": json.dumps({
                "function": "process_data",
                "avg_time_ms": 12.5,
                "memory_peak_mb": 3.45,
                "iterations": 100,
            }) + "\n",
            "stderr": "",
            "error": None,
        }
        with patch("agent.nodes.runner.run_benchmark", new_callable=AsyncMock, return_value=modal_output):
            result = await run_benchmarks_node(self._make_state())

        r = result["initial_results"][0]
        assert r["memory_peak_mb"] == 3.45
        assert r["avg_time_ms"] == 12.5

    async def test_memory_defaults_to_zero_on_error(self):
        from unittest.mock import AsyncMock
        from agent.nodes.runner import run_benchmarks_node

        modal_output = {
            "stdout": "",
            "stderr": "ModuleNotFoundError",
            "error": "Exit code 1: ModuleNotFoundError",
        }
        with patch("agent.nodes.runner.run_benchmark", new_callable=AsyncMock, return_value=modal_output):
            result = await run_benchmarks_node(self._make_state())

        r = result["initial_results"][0]
        assert r["memory_peak_mb"] == 0

    async def test_multiline_stdout_with_memory(self):
        from unittest.mock import AsyncMock
        from agent.nodes.runner import run_benchmarks_node

        modal_output = {
            "stdout": "Loading data...\nProcessing...\n" + json.dumps({
                "function": "process_data",
                "avg_time_ms": 8.0,
                "memory_peak_mb": 2.1,
                "iterations": 50,
            }) + "\n",
            "stderr": "",
            "error": None,
        }
        with patch("agent.nodes.runner.run_benchmark", new_callable=AsyncMock, return_value=modal_output):
            result = await run_benchmarks_node(self._make_state())

        r = result["initial_results"][0]
        assert r["memory_peak_mb"] == 2.1
        assert r["avg_time_ms"] == 8.0


# ---------------------------------------------------------------------------
# Wrapper constant sanity checks
# ---------------------------------------------------------------------------


class TestWrapperConstants:
    """Basic sanity checks that the wrapper strings are valid."""

    def test_python_wrapper_is_valid_python(self):
        from services.modal_service import PYTHON_MEMORY_WRAPPER
        compile(PYTHON_MEMORY_WRAPPER, "<python_wrapper>", "exec")

    def test_python_wrapper_uses_tracemalloc(self):
        from services.modal_service import PYTHON_MEMORY_WRAPPER
        assert "tracemalloc" in PYTHON_MEMORY_WRAPPER
        assert "_tracemalloc.start()" in PYTHON_MEMORY_WRAPPER
        assert "_tracemalloc.get_traced_memory()" in PYTHON_MEMORY_WRAPPER

    def test_python_wrapper_references_inner_script(self):
        from services.modal_service import PYTHON_MEMORY_WRAPPER
        assert "_benchmark_inner.py" in PYTHON_MEMORY_WRAPPER

    def test_js_wrapper_uses_memory_usage(self):
        from services.modal_service import JS_MEMORY_WRAPPER
        assert "process.memoryUsage().heapUsed" in JS_MEMORY_WRAPPER

    def test_js_wrapper_references_inner_script(self):
        from services.modal_service import JS_MEMORY_WRAPPER
        assert "_benchmark_inner.js" in JS_MEMORY_WRAPPER

    def test_js_wrapper_patches_memory_peak_mb(self):
        from services.modal_service import JS_MEMORY_WRAPPER
        assert "memory_peak_mb" in JS_MEMORY_WRAPPER
