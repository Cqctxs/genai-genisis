"""Tests for performance optimizations: model selection and API call batching.

Validates that:
1. Chunk analysis uses Flash (not Pro) for faster hotspot detection.
2. Benchmark generation batches hotspots into fewer API calls.
3. Output format remains compatible with downstream pipeline nodes.
"""
import asyncio
import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.schemas import (
    AnalysisResult,
    BenchmarkBatch,
    BenchmarkScript,
    Hotspot,
    TriageChunk,
    TriageResult,
)

pytestmark = pytest.mark.anyio


def _make_hotspot(name: str, file: str = "app.py", severity: str = "high") -> Hotspot:
    return Hotspot(
        function_name=name,
        file=file,
        severity=severity,
        category="O(n^2) loop",
        reasoning="Nested loop over large dataset",
    )


def _make_benchmark_script(name: str, file: str = "app.py") -> BenchmarkScript:
    return BenchmarkScript(
        target_function=name,
        file=file,
        language="python",
        script_content=f"print('bench {name}')",
        description=f"Benchmark for {name}",
    )


# ---------------------------------------------------------------------------
# Schema: BenchmarkBatch
# ---------------------------------------------------------------------------


class TestBenchmarkBatchSchema:
    def test_round_trip_serialization(self):
        scripts = [_make_benchmark_script("fn_a"), _make_benchmark_script("fn_b")]
        batch = BenchmarkBatch(scripts=scripts)
        data = batch.model_dump()
        restored = BenchmarkBatch(**data)

        assert len(restored.scripts) == 2
        assert restored.scripts[0].target_function == "fn_a"
        assert restored.scripts[1].target_function == "fn_b"

    def test_empty_batch(self):
        batch = BenchmarkBatch(scripts=[])
        assert len(batch.scripts) == 0

    def test_single_item_batch(self):
        batch = BenchmarkBatch(scripts=[_make_benchmark_script("only")])
        assert len(batch.scripts) == 1
        assert batch.scripts[0].target_function == "only"


# ---------------------------------------------------------------------------
# Model Selection: Chunk analysis must use Flash, not Pro
# ---------------------------------------------------------------------------


class TestAnalysisUsesFlash:
    async def test_analyze_chunk_creates_flash_agent(self):
        """_analyze_chunk must call get_agent with GEMINI_FLASH, not GEMINI_PRO."""
        from agent.nodes.analyzer import _analyze_chunk
        from services.gemini_service import GEMINI_FLASH

        chunk = TriageChunk(
            chunk_id="test_chunk",
            label="Test Chunk",
            files=["app.py"],
            priority=1,
            reasoning="Test",
        )
        ast_map = {"functions": [], "classes": [], "imports": [], "call_edges": []}

        fake_analysis = AnalysisResult(
            language="python",
            hotspots=[_make_hotspot("fn_a")],
            summary="test",
        )
        mock_result = MagicMock()
        mock_result.output = fake_analysis

        with (
            patch("agent.nodes.analyzer.read_file", return_value="def fn_a(): pass"),
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()) as mock_get_agent,
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result),
        ):
            await _analyze_chunk(chunk, ast_map, "/tmp/fake", "python")
            mock_get_agent.assert_called_once()
            _, _, model_arg = mock_get_agent.call_args[0]
            assert model_arg == GEMINI_FLASH, (
                f"Expected GEMINI_FLASH ({GEMINI_FLASH}), got {model_arg}"
            )

    async def test_analyze_chunk_does_not_use_pro(self):
        """Ensure GEMINI_PRO is not referenced in analyze_chunk calls."""
        from agent.nodes.analyzer import _analyze_chunk
        from services.gemini_service import GEMINI_PRO

        chunk = TriageChunk(
            chunk_id="c1", label="C1", files=["x.py"], priority=1, reasoning="t",
        )
        ast_map = {"functions": [], "classes": [], "imports": [], "call_edges": []}

        mock_result = MagicMock()
        mock_result.output = AnalysisResult(
            language="python", hotspots=[], summary="none",
        )

        with (
            patch("agent.nodes.analyzer.read_file", return_value="pass"),
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()) as mock_get_agent,
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result),
        ):
            await _analyze_chunk(chunk, ast_map, "/tmp/fake", "python")
            _, _, model_arg = mock_get_agent.call_args[0]
            assert model_arg != GEMINI_PRO


# ---------------------------------------------------------------------------
# Batching: _generate_benchmark_batch
# ---------------------------------------------------------------------------


class TestBenchmarkBatching:
    async def test_batch_returns_scripts_from_single_call(self):
        """A batch of N hotspots should produce N scripts from 1 API call."""
        from agent.nodes.analyzer import _generate_benchmark_batch

        hotspots = [_make_hotspot("fn_a"), _make_hotspot("fn_b"), _make_hotspot("fn_c")]
        batch_output = BenchmarkBatch(scripts=[
            _make_benchmark_script("fn_a"),
            _make_benchmark_script("fn_b"),
            _make_benchmark_script("fn_c"),
        ])

        mock_result = MagicMock()
        mock_result.output = batch_output

        with (
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result) as mock_run,
        ):
            scripts = await _generate_benchmark_batch(
                hotspots, "python", {"functions": [], "classes": [], "imports": []}, batch_index=0, repo_files={}
            )
            assert len(scripts) == 3
            assert scripts[0].target_function == "fn_a"
            assert scripts[2].target_function == "fn_c"
            mock_run.assert_awaited_once()

    async def test_batch_uses_benchmark_batch_output_type(self):
        """The agent must be created with BenchmarkBatch output type."""
        from agent.nodes.analyzer import _generate_benchmark_batch

        hotspots = [_make_hotspot("fn_x")]
        mock_result = MagicMock()
        mock_result.output = BenchmarkBatch(scripts=[_make_benchmark_script("fn_x")])

        with (
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()) as mock_get_agent,
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result),
        ):
            await _generate_benchmark_batch(
                hotspots, "python", {"functions": [], "classes": [], "imports": []}, batch_index=0, repo_files={}
            )
            output_type_arg = mock_get_agent.call_args[0][0]
            assert output_type_arg is BenchmarkBatch

    async def test_batch_failure_returns_empty_list(self):
        """If the API call fails, the batch should return [] without raising."""
        from agent.nodes.analyzer import _generate_benchmark_batch

        hotspots = [_make_hotspot("fn_fail")]

        with (
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, side_effect=RuntimeError("API error")),
        ):
            scripts = await _generate_benchmark_batch(
                hotspots, "python", {"functions": [], "classes": [], "imports": []}, batch_index=0, repo_files={}
            )
            assert scripts == []

    async def test_batch_prompt_includes_all_hotspots(self):
        """The prompt sent to the model must mention every hotspot in the batch."""
        from agent.nodes.analyzer import _generate_benchmark_batch

        hotspots = [_make_hotspot("alpha"), _make_hotspot("beta"), _make_hotspot("gamma")]
        mock_result = MagicMock()
        mock_result.output = BenchmarkBatch(scripts=[
            _make_benchmark_script(h.function_name) for h in hotspots
        ])

        with (
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result) as mock_run,
        ):
            await _generate_benchmark_batch(
                hotspots, "python", {"functions": [], "classes": [], "imports": []}, batch_index=0, repo_files={}
            )
            prompt_arg = mock_run.call_args[0][1]
            assert "alpha" in prompt_arg
            assert "beta" in prompt_arg
            assert "gamma" in prompt_arg
            assert "3 hotspot(s)" in prompt_arg


# ---------------------------------------------------------------------------
# Integration: chunk_analyze_node batches correctly
# ---------------------------------------------------------------------------


class TestChunkAnalyzeNodeBatching:
    def _make_state(self, num_hotspots: int = 6) -> dict:
        """Build a minimal state dict with a triage result."""
        triage = TriageResult(
            language="python",
            chunks=[
                TriageChunk(
                    chunk_id="c1",
                    label="Core",
                    files=["app.py"],
                    priority=1,
                    reasoning="Main app",
                ),
            ],
            total_files_scanned=1,
            summary="test",
        )
        return {
            "triage_result": triage.model_dump(),
            "ast_map": {"functions": [], "classes": [], "imports": [], "call_edges": []},
            "repo_path": "/tmp/fake",
            "messages": [],
        }

    async def test_hotspots_batched_by_batch_size(self):
        """With 7 hotspots and BENCHMARK_BATCH_SIZE=4, expect 2 batch calls."""
        from agent.nodes.analyzer import chunk_analyze_node, BENCHMARK_BATCH_SIZE

        hotspots = [_make_hotspot(f"fn_{i}") for i in range(7)]

        fake_analysis = AnalysisResult(language="python", hotspots=hotspots, summary="test")
        mock_analysis_result = MagicMock()
        mock_analysis_result.output = fake_analysis

        batch_call_count = 0
        batch_sizes_seen = []

        async def fake_generate_batch(batch_hotspots, language, ast_map, batch_index):
            nonlocal batch_call_count
            batch_call_count += 1
            batch_sizes_seen.append(len(batch_hotspots))
            return [_make_benchmark_script(h.function_name) for h in batch_hotspots]

        with (
            patch("agent.nodes.analyzer.read_file", return_value="pass"),
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_analysis_result),
            patch("agent.nodes.analyzer._generate_benchmark_batch", side_effect=fake_generate_batch),
        ):
            result = await chunk_analyze_node(self._make_state())

        expected_batches = math.ceil(7 / BENCHMARK_BATCH_SIZE)
        assert batch_call_count == expected_batches, (
            f"Expected {expected_batches} batch calls, got {batch_call_count}"
        )
        assert batch_sizes_seen == [BENCHMARK_BATCH_SIZE, 7 - BENCHMARK_BATCH_SIZE]
        assert len(result["benchmark_code"]) == 7

    async def test_output_format_compatible_with_runner(self):
        """benchmark_code entries must be dicts parseable as BenchmarkScript."""
        from agent.nodes.analyzer import chunk_analyze_node

        hotspots = [_make_hotspot("fn_0")]
        fake_analysis = AnalysisResult(language="python", hotspots=hotspots, summary="t")
        mock_result = MagicMock()
        mock_result.output = fake_analysis

        async def fake_batch(hs, lang, ast, idx):
            return [_make_benchmark_script(h.function_name) for h in hs]

        with (
            patch("agent.nodes.analyzer.read_file", return_value="pass"),
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result),
            patch("agent.nodes.analyzer._generate_benchmark_batch", side_effect=fake_batch),
        ):
            result = await chunk_analyze_node(self._make_state())

        for entry in result["benchmark_code"]:
            script = BenchmarkScript(**entry)
            assert script.target_function
            assert script.file
            assert script.language
            assert script.script_content

    async def test_zero_hotspots_produces_zero_batches(self):
        """If analysis finds no hotspots, benchmark generation should not be called."""
        from agent.nodes.analyzer import chunk_analyze_node

        fake_analysis = AnalysisResult(language="python", hotspots=[], summary="clean")
        mock_result = MagicMock()
        mock_result.output = fake_analysis

        with (
            patch("agent.nodes.analyzer.read_file", return_value="pass"),
            patch("agent.nodes.analyzer.get_agent", return_value=MagicMock()),
            patch("agent.nodes.analyzer.run_agent_logged", new_callable=AsyncMock, return_value=mock_result),
            patch("agent.nodes.analyzer._generate_benchmark_batch", new_callable=AsyncMock) as mock_batch,
        ):
            result = await chunk_analyze_node(self._make_state())

        mock_batch.assert_not_awaited()
        assert result["benchmark_code"] == []


# ---------------------------------------------------------------------------
# Regression: verify GEMINI_PRO is NOT imported in analyzer.py
# ---------------------------------------------------------------------------


class TestAnalyzerImports:
    def test_gemini_pro_not_imported(self):
        """analyzer.py should not import GEMINI_PRO after the model selection change."""
        import agent.nodes.analyzer as analyzer_module
        assert not hasattr(analyzer_module, "GEMINI_PRO"), (
            "GEMINI_PRO should not be imported in analyzer.py"
        )

    def test_gemini_flash_is_imported(self):
        import agent.nodes.analyzer as analyzer_module
        from services.gemini_service import GEMINI_FLASH
        assert hasattr(analyzer_module, "GEMINI_FLASH")

    def test_benchmark_batch_size_is_positive(self):
        from agent.nodes.analyzer import BENCHMARK_BATCH_SIZE
        assert BENCHMARK_BATCH_SIZE > 0
        assert isinstance(BENCHMARK_BATCH_SIZE, int)
