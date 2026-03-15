# Benchmark Runtime Errors Fix Plan

This plan addresses the two specific runtime errors encountered during benchmark execution.

## Issue 1: `data_generator` Module Not Found / Relative Import Failure
**Root Cause:**
The benchmark script attempts to import modules from the target repository (e.g., `import advanced_demo.main`). However, due to the way Python resolves imports in the temporary execution directory, it can sometimes pull from system-installed site-packages (like a system `data_generator` package) instead of the local repository files, especially when `__init__.py` files are absent or `sys.path` is not properly configured.

**Step-by-Step Fix:**
1. **Locate Sandbox/Execution Code**: Open `backend/services/modal_service.py` (or where the benchmark script is executed in isolated environments).
2. **Set PYTHONPATH**: Modify the execution environment configuration to explicitly add the root of the extracted repository to the `PYTHONPATH` environment variable. This ensures Python looks for modules in the repository structure first before checking system packages.
3. **Prompt Instruction (Optional)**: If setting `PYTHONPATH` is not sufficient, update `backend/agent/nodes/benchmarker.py` to instruct the LLM to insert the repository path into `sys.path` at the very beginning of the benchmark script.

## Issue 2: Mock Objects Missing `__name__` Attribute
**Root Cause:**
When the initial benchmark fails (due to Issue 1), the system attempts a retry. Gemini tries to fix the import error by heavily mocking dependencies (e.g., mocking `parse_data` with `MagicMock`). This mock object is then passed into `measure_performance(func, ...)`, which executes `print(f"Running {func.__name__}...")`. Standard mock objects do not have a `__name__` attribute, leading to an `AttributeError`.

**Step-by-Step Fix:**
1. **Locate Benchmark Prompt**: Open `backend/agent/nodes/benchmarker.py`.
2. **Update BENCHMARK_PROMPT**: Add explicit instructions regarding the mocking of functions. Add a rule stating: 
   > "If you use `unittest.mock.patch` or `MagicMock` to mock functions that are passed as arguments to other functions, you MUST explicitly assign a `__name__` attribute to the mock object (e.g., `mock_function.__name__ = 'my_function'`) to prevent `AttributeError` during introspection."
3. **Discourage Aggressive Mocking**: Add a soft constraint in the prompt to prefer executing the actual code rather than overly mocking internal target functions, so long as it doesn't hang or destroy the environment.

*Note: Only these two issues will be addressed to ensure no other systems are broken.*

---

## Change Log

### Issue 1 Fixes

**File: `backend/services/modal_service.py`** (line ~227)
- **Change**: Added `PYTHONPATH` environment variable to the subprocess execution in `_run_python_benchmark`.
- **What was added**: Before the `for _ in range(3)` retry loop, an `env` dict is now created via `os.environ.copy()` with `PYTHONPATH` prepended to the workdir path. This `env` is passed to `subprocess.run(..., env=env)`.
- **Why**: Ensures that Python's module resolver looks in the repo's working directory first before falling back to system site-packages. This prevents the `ModuleNotFoundError` caused by system packages (e.g., a system `data_generator`) shadowing the repo's local modules.

**File: `backend/agent/nodes/benchmarker.py`** (BENCHMARK_PROMPT, Sandbox Environment section)
- **Change**: Added prompt instruction telling the LLM to begin every Python benchmark script with `import sys, os; sys.path.insert(0, os.getcwd())`.
- **What was added**: A new bullet point in the Sandbox Environment section explaining that PYTHONPATH is set but the script should also insert `os.getcwd()` into `sys.path` as a belt-and-suspenders safeguard.
- **Why**: Even with PYTHONPATH set at the subprocess level, having `sys.path.insert(0, ...)` in the script itself provides a second layer of protection against import resolution issues.

### Issue 2 Fixes

**File: `backend/agent/nodes/benchmarker.py`** (BENCHMARK_PROMPT, Sandbox Environment section)
- **Change 1**: Added a `CRITICAL MOCK RULE` bullet requiring `__name__` be set on any `MagicMock` that gets passed as a function argument.
- **What was added**: `"If you use unittest.mock.patch or MagicMock to mock functions that are passed as arguments to other functions, you MUST explicitly assign a __name__ attribute to the mock object (e.g., mock_function.__name__ = 'my_function') to prevent AttributeError during introspection such as func.__name__."`
- **Why**: When Gemini mocks a function and passes it to `measure_performance(func, ...)`, the benchmark wrapper accesses `func.__name__`. Standard `MagicMock` does not have `__name__`, causing `AttributeError`. This instruction prevents that.

- **Change 2**: Added a `PREFER REAL CODE OVER MOCKING` bullet discouraging aggressive mocking of internal target functions.
- **What was added**: `"Do NOT aggressively mock internal target functions. Always prefer executing the actual repository code. Only mock external dependencies (network, database, file system) that would hang or destroy the environment. Mocking the function you are benchmarking defeats the purpose of the benchmark."`
- **Why**: Reduces the likelihood of the LLM over-mocking, which caused Issue 2 in the first place. The retry logic was producing heavily mocked benchmarks that were functionally useless.

**File: `backend/agent/nodes/runner.py`** (`_regenerate_benchmark` function, AttributeError handling)
- **Change**: Expanded the `AttributeError` retry guidance to include explicit `__name__` assignment instructions and a preference for running real code.
- **What was added**: The `is_attribute_error` block now includes a code example showing `mock_fn.__name__ = 'original_function_name'` and a directive to prefer running the actual target function rather than mocking it.
- **Why**: When a benchmark fails with `AttributeError` and the retry kicks in, Gemini now receives clearer guidance on how to fix the mock issue specifically, reducing the chance of a second failure.

### Test Verification

- **Baseline (before changes)**: 117 passed, 7 pre-existing failures (unrelated to these issues).
- **After changes**: 117 passed, same 7 pre-existing failures. **Zero regressions introduced.**
- Pre-existing failures are in `test_performance_optimizations.py` (3, related to streaming pipeline signature mismatch) and `test_scoring_service.py` (4, related to noise-floor scoring edge cases). None are related to the benchmark runtime error fixes.
