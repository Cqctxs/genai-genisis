"""Tests validating each bugfix doesn't break existing behaviour."""
import asyncio
import json
import os
import tempfile
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# Bug 1: should_retry must respect retry_count and rerun_benchmarks_node
#         must increment it.  Previously retry_count was never incremented,
#         causing an infinite optimize ↔ rerun loop.
# ---------------------------------------------------------------------------


class TestShouldStopRetrying:
    """Verify _should_stop_retrying honours retry_count and result quality."""

    def _make_state(self, **overrides):
        from agent.state import AgentState

        base: AgentState = {
            "initial_results": [{"avg_time_ms": 100}],
            "final_results": [{"avg_time_ms": 200}],
            "retry_count": 0,
        }
        base.update(overrides)
        return base

    def test_stops_when_retry_count_exceeds_max(self):
        from agent.graph import _should_stop_retrying, MAX_OPTIMIZATION_RETRIES

        state = self._make_state(retry_count=MAX_OPTIMIZATION_RETRIES)
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is True

    def test_stops_when_retry_count_equals_max(self):
        from agent.graph import _should_stop_retrying, MAX_OPTIMIZATION_RETRIES

        state = self._make_state(retry_count=MAX_OPTIMIZATION_RETRIES)
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is True

    def test_retries_when_no_improvement_and_retries_left(self):
        from agent.graph import _should_stop_retrying

        state = self._make_state(
            initial_results=[{"avg_time_ms": 100}],
            final_results=[{"avg_time_ms": 200}],
            retry_count=0,
        )
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is False

    def test_stops_when_improvement_achieved(self):
        from agent.graph import _should_stop_retrying

        state = self._make_state(
            initial_results=[{"avg_time_ms": 200}],
            final_results=[{"avg_time_ms": 100}],
            retry_count=0,
        )
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is True

    def test_stops_when_no_initial_results(self):
        from agent.graph import _should_stop_retrying

        state = self._make_state(initial_results=[], final_results=[{"avg_time_ms": 1}])
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is True

    def test_stops_when_no_final_results(self):
        from agent.graph import _should_stop_retrying

        state = self._make_state(initial_results=[{"avg_time_ms": 1}], final_results=[])
        should_stop, _ = _should_stop_retrying(state)
        assert should_stop is True


class TestRerunBenchmarksIncrementsRetryCount:
    """Verify _rerun_benchmarks bumps retry_count each invocation."""

    async def test_retry_count_incremented(self):
        from agent.graph import _rerun_benchmarks

        fake_run_result = {
            "final_results": [{"avg_time_ms": 42}],
            "messages": ["done"],
        }
        with patch("agent.graph.run_benchmarks_node", new_callable=AsyncMock, return_value=fake_run_result):
            state = {
                "repo_path": "/tmp/nonexistent",
                "optimized_files": {},
                "initial_results": [{"avg_time_ms": 100}],
                "messages": ["prior"],
                "retry_count": 0,
            }
            result = await _rerun_benchmarks(state)
            assert result["retry_count"] == 1

            state2 = {**state, "retry_count": 1}
            result2 = await _rerun_benchmarks(state2)
            assert result2["retry_count"] == 2


# ---------------------------------------------------------------------------
# Bug 2: clone_repo must not block the event loop.  It should delegate the
#         synchronous Repo.clone_from to asyncio.to_thread.
# ---------------------------------------------------------------------------


class TestCloneRepoNonBlocking:
    async def test_clone_uses_to_thread(self):
        from services.github_service import clone_repo

        with (
            patch("services.github_service.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
            patch("services.github_service.tempfile.mkdtemp", return_value="/tmp/codemark_test"),
        ):
            mock_to_thread.return_value = MagicMock()
            result = await clone_repo("https://github.com/user/repo", "ghp_token123")

            mock_to_thread.assert_awaited_once()
            args = mock_to_thread.call_args
            assert args[0][0].__name__ == "clone_from"
            assert result == "/tmp/codemark_test"


# ---------------------------------------------------------------------------
# Bug 3: SSE event data must be JSON for dicts/lists, not Python repr.
#         Previously str(dict) produced "{'key': 'value'}" which is not
#         parseable by JSON.parse() on the frontend.
# ---------------------------------------------------------------------------


class TestSSESerialization:
    def test_dict_data_serialized_as_json(self):
        """Dicts must produce valid JSON, not Python repr."""
        import main
        from starlette.testclient import TestClient

        job_id = "test-sse-dict"
        queue = asyncio.Queue()
        main.job_queues[job_id] = queue
        main.jobs[job_id] = {"status": "running"}

        test_data = {"key": "value", "nested": {"a": 1}}
        queue.put_nowait({"event": "complete", "data": test_data})

        client = TestClient(main.app)
        with client.stream("GET", f"/api/stream/{job_id}") as response:
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)

        data_lines = [l for l in lines if l.startswith("data:")]
        assert len(data_lines) >= 1
        raw = data_lines[-1].removeprefix("data:").strip()
        parsed = json.loads(raw)
        assert parsed == test_data

        main.jobs.pop(job_id, None)

    def test_string_data_passed_through(self):
        """String data (e.g. progress events) must pass through as-is."""
        import main
        from starlette.testclient import TestClient

        job_id = "test-sse-str"
        queue = asyncio.Queue()
        main.job_queues[job_id] = queue
        main.jobs[job_id] = {"status": "running"}

        json_str = json.dumps({"node": "analyze", "message": "found 3 hotspots"})
        queue.put_nowait({"event": "progress", "data": json_str})
        queue.put_nowait({"event": "complete", "data": {"done": True}})

        client = TestClient(main.app)
        with client.stream("GET", f"/api/stream/{job_id}") as response:
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)

        data_lines = [l for l in lines if l.startswith("data:")]
        progress_raw = data_lines[0].removeprefix("data:").strip()
        assert progress_raw == json_str

        main.jobs.pop(job_id, None)


# ---------------------------------------------------------------------------
# Bug 4: Queue must be cleaned up after the SSE stream finishes, preventing
#         unbounded memory growth.
# ---------------------------------------------------------------------------


class TestQueueCleanup:
    def test_queue_removed_after_stream_completes(self):
        import main
        from starlette.testclient import TestClient

        job_id = "test-cleanup"
        queue = asyncio.Queue()
        main.job_queues[job_id] = queue
        main.jobs[job_id] = {"status": "running"}

        queue.put_nowait({"event": "complete", "data": {"result": "ok"}})

        client = TestClient(main.app)
        with client.stream("GET", f"/api/stream/{job_id}") as response:
            for _ in response.iter_lines():
                pass

        assert job_id not in main.job_queues

        main.jobs.pop(job_id, None)


# ---------------------------------------------------------------------------
# Bug 5: parser_service call edges must have non-empty callers when calls
#         are inside a function.  Previously every edge was ("", callee).
# ---------------------------------------------------------------------------


class TestParserCallEdgesHaveCaller:
    def test_python_calls_inside_function_have_caller(self):
        from services.parser_service import parse_file

        src = textwrap.dedent("""\
            def outer():
                inner()

            def inner():
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            path = f.name

        try:
            result = parse_file(path, "test.py")
            calls = result["calls"]
            inner_calls = [(caller, callee) for caller, callee in calls if callee == "inner"]
            assert len(inner_calls) >= 1
            assert inner_calls[0][0] == "outer", f"Expected caller='outer', got '{inner_calls[0][0]}'"
        finally:
            os.unlink(path)

    def test_python_toplevel_call_has_empty_caller(self):
        from services.parser_service import parse_file

        src = textwrap.dedent("""\
            def greet():
                pass

            greet()
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            path = f.name

        try:
            result = parse_file(path, "test.py")
            calls = result["calls"]
            greet_calls = [(caller, callee) for caller, callee in calls if callee == "greet"]
            assert len(greet_calls) >= 1
            assert greet_calls[0][0] == "", "Top-level call should have empty caller"
        finally:
            os.unlink(path)

    def test_js_calls_inside_function_have_caller(self):
        from services.parser_service import parse_file

        src = textwrap.dedent("""\
            function fetchData() {
                processResponse();
            }

            function processResponse() {}
        """)
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            path = f.name

        try:
            result = parse_file(path, "test.js")
            calls = result["calls"]
            process_calls = [(c, e) for c, e in calls if e == "processResponse"]
            assert len(process_calls) >= 1
            assert process_calls[0][0] == "fetchData", f"Expected caller='fetchData', got '{process_calls[0][0]}'"
        finally:
            os.unlink(path)

    def test_python_nested_call_resolves_to_immediate_enclosing(self):
        from services.parser_service import parse_file

        src = textwrap.dedent("""\
            def outer():
                def middle():
                    target()
                middle()
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            f.flush()
            path = f.name

        try:
            result = parse_file(path, "test.py")
            calls = result["calls"]
            target_calls = [(c, e) for c, e in calls if e == "target"]
            assert len(target_calls) >= 1
            assert target_calls[0][0] == "middle", f"Expected caller='middle', got '{target_calls[0][0]}'"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Bug 6 & 7: Verify that cleaned-up modules import without error.
# ---------------------------------------------------------------------------


class TestCleanImports:
    def test_gemini_service_imports(self):
        import services.gemini_service  # noqa: F401

    def test_modal_service_imports(self):
        import services.modal_service  # noqa: F401

    def test_parser_service_imports(self):
        import services.parser_service  # noqa: F401


# ---------------------------------------------------------------------------
# Regression: Ensure github_service utility functions still work correctly
#             after adding asyncio import and changing clone_repo.
# ---------------------------------------------------------------------------


class TestGithubServiceUtilities:
    def test_inject_token_standard_url(self):
        from services.github_service import _inject_token

        result = _inject_token("https://github.com/user/repo", "ghp_abc123")
        assert result == "https://x-access-token:ghp_abc123@github.com/user/repo"

    def test_inject_token_non_github_url(self):
        from services.github_service import _inject_token

        result = _inject_token("https://gitlab.com/user/repo", "ghp_abc123")
        assert result == "https://gitlab.com/user/repo"

    def test_get_file_tree(self):
        from services.github_service import get_file_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"))
            with open(os.path.join(tmpdir, "src", "app.py"), "w") as f:
                f.write("pass")
            with open(os.path.join(tmpdir, "src", "app.js"), "w") as f:
                f.write("//")
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# hi")

            tree = get_file_tree(tmpdir)
            assert "src/app.py" in tree
            assert "src/app.js" in tree
            assert "README.md" not in tree

    def test_read_file(self):
        from services.github_service import read_file

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "hello.py"), "w") as f:
                f.write("print('hello')")

            content = read_file(tmpdir, "hello.py")
            assert content == "print('hello')"

    def test_cleanup_repo(self):
        from services.github_service import cleanup_repo

        tmpdir = tempfile.mkdtemp()
        with open(os.path.join(tmpdir, "file.txt"), "w") as f:
            f.write("data")
        assert os.path.exists(tmpdir)

        cleanup_repo(tmpdir)
        assert not os.path.exists(tmpdir)


# ---------------------------------------------------------------------------
# Regression: AgentState should still be a valid TypedDict with retry_count
# ---------------------------------------------------------------------------


class TestAgentState:
    def test_retry_count_field_exists(self):
        from agent.state import AgentState

        hints = AgentState.__annotations__
        assert "retry_count" in hints
        assert hints["retry_count"] is int

    def test_state_is_optional(self):
        """All AgentState fields are optional (total=False)."""
        from agent.state import AgentState

        state: AgentState = {}
        assert state.get("retry_count", 0) == 0
        assert state.get("messages", []) == []


# ---------------------------------------------------------------------------
# Issue 1: _run_agent must receive the queue directly, not look it up from
#           the global dict.  A client disconnect before task start would pop
#           the queue and cause a KeyError.
# ---------------------------------------------------------------------------


class TestRunAgentReceivesQueue:
    async def test_run_agent_uses_passed_queue_not_dict(self):
        """_run_agent should use the queue arg, not look it up from job_queues."""
        import main

        job_id = "test-queue-pass"
        queue = asyncio.Queue()
        main.jobs[job_id] = {"status": "pending", "result": None}

        fake_result = {"graph_data": {}, "comparison": {}}
        with patch("agent.graph.run_optimization_pipeline", new_callable=AsyncMock, return_value=fake_result):
            await main._run_agent(job_id, "https://github.com/x/y", "tok", queue)

        assert main.jobs[job_id]["status"] == "completed"
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert msg["event"] == "complete"

        main.jobs.pop(job_id, None)

    async def test_run_agent_works_even_if_queue_popped_from_dict(self):
        """Even if job_queues no longer has the entry, _run_agent succeeds."""
        import main

        job_id = "test-queue-popped"
        queue = asyncio.Queue()
        main.jobs[job_id] = {"status": "pending", "result": None}
        main.job_queues.pop(job_id, None)

        fake_result = {"graph_data": {}}
        with patch("agent.graph.run_optimization_pipeline", new_callable=AsyncMock, return_value=fake_result):
            await main._run_agent(job_id, "https://github.com/x/y", "tok", queue)

        assert main.jobs[job_id]["status"] == "completed"
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert msg["event"] == "complete"

        main.jobs.pop(job_id, None)


# ---------------------------------------------------------------------------
# Issue 2: cleanup is now inline in optimization_pipeline (no standalone
#           cleanup_node).  The pipeline calls:
#               await asyncio.to_thread(cleanup_repo, repo_path)
#           cleanup_repo itself is tested in TestGithubServiceUtilities.
# ---------------------------------------------------------------------------
