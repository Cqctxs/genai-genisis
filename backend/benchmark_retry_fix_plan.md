# Benchmark ModuleNotFoundError and Retry Loop Fix Plan

This document outlines the step-by-step plan to resolve the repeated `ModuleNotFoundError` issues observed in the benchmarking pipeline, particularly when local modules (such as `database`) fail to import and trigger a repetitive `pip install` loop.

## 1. Problem Analysis & Root Cause

The issue is characterized by three compounding factors:

1. **Failure to Distinguish Local vs. External Modules**: The retry logic in the sandbox execution service catches `ModuleNotFoundError`, extracts the module name (e.g., `'database'`), and automatically attempts to `pip install` it. However, local files from the user's repository (like `database.py`) cannot be installed via `pip`, leading to silent/repeated failures.
2. **Missing Local Files in Sandbox Context**: Code mapped via `repo_files` is written to a temporary execution directory. Sometimes, specific package structures or utility files without standard extensions or without `__init__.py` files aren't adequately discovered or configured in the Python path when executing the benchmark shell script.
3. **Redundant Repetitive Retries**: The system attempts to retry 3 times without any secondary checks. Because the error is deterministic (the local file can't be pip installed and isn't on `sys.path`), the exact same error output is repeated in the logs for all 3 attempts.

---

## 2. Step-by-Step Implementation Plan

### Step 2.1: Extract List of Local Modules
**Goal**: Build a list of valid local module names based on the files cloned from the user's repository.
- **Where**: `backend/agent/nodes/runner.py` (or where the file tree is resolved).
- **Action**: Parse `state["repo_files"]` to identify top-level Python modules and directory names. Keep an array/set of these module names (e.g., `["server", "database", "data_generator", "benchmark"]`).

### Step 2.2: Refine Retry Logic to Fail Fast on Local Modules
**Goal**: Update the retry mechanism to immediately recognize when a local module is missing rather than attempting to `pip install` it blindly.
- **Where**: `backend/services/modal_service.py` (or the specific service executing the benchmark).
- **Action**: 
  - Update the `ModuleNotFoundError` regex extractor.
  - Check if the missing module name exists in the local repo structure.
  - **If External**: Proceed with `pip install {package_name}` and retry as usual.
  - **If Local**: Skip the `pip install`. Fast-fail the benchmark or explicitly attempt to inject `PYTHONPATH` fixes instead, logging: `"Local module '{module_name}' failed to resolve. Check sys.path."`

### Step 2.3: Correct Sandbox `PYTHONPATH` Configuration
**Goal**: Ensure the execution directory dynamically generated in the sandbox environment is properly set up so relative and root imports work as expected out-of-the-box.
- **Where**: The sandbox script runner function (likely in `backend/services/modal_service.py` where the temp dir `cd` command is created).
- **Action**:
  - Dynamically prepend or configure `PYTHONPATH=$PWD` or `PYTHONPATH=/tmp/<sandbox_dir>` in the bash script right before calling `python _benchmark.py`.
  - Ensure that if `advanced_demo/server.py` attempts to do `import database`, that `advanced_demo` is treated as a package, and the root is in `sys.path`.

### Step 2.4: Ensure Comprehensive Sandbox File Sync
**Goal**: Prevent silent dropping of critical files when building the sandbox.
- **Where**: The `get_file_tree` or `repo_files` injection code.
- **Action**: 
  - Ensure missing files don't fail silently (currently `except Exception: pass` is hiding tracebacks).
  - Verify that `__init__.py` files are copied over to the sandbox to preserve Python package structure, otherwise `import advanced_demo.server` will fail in Python < 3.3, and might still struggle natively depending on module tree context.

---

## 3. Verification Scenarios

Once the above changes are made, run the following verification steps:
1. **Local Import test**: Trigger the `advanced_demo/server.py` benchmark. Ensure the local `database` module resolves correctly without throwing `ModuleNotFoundError`.
2. **True External Package Missing test**: Create a benchmark that intentionally imports an obscure missing PyPI package (e.g., `import some_random_package`). Verify that the system correctly attempts to `pip install` it, and successfully retries.
3. **Fail Fast local test**: Intentionally delete `database.py` while keeping the import in `server.py`. Ensure the system halts the sequence quickly, recognizing `database` is a repository module and DOES NOT repeat the installation error 3 times.