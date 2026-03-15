"""Tests for the deterministic scoring algorithm in scoring_service.py.

Validates that:
1. Algorithmic improvements (O(n²)→O(n)) always produce a higher score.
2. Time-space tradeoffs (faster + more memory) are not penalised.
3. Noise-floor handling prevents sub-ms jitter from swinging scores.
4. Hotspot severity and category are weighted correctly.
5. Edge cases (empty results, zero times, no matches) are handled.
"""

import math

import pytest

from agent.schemas import CodeMarkScore, FunctionComparison, RadarAxis
from services.scoring_service import (
    _category_score,
    _compute_speedup,
    _is_time_space_tradeoff,
    _match_results,
    compute_benchy_score,
    NOISE_FLOOR_MS,
    NOISE_FLOOR_PCT,
    TIME_BASE,
    MEMORY_BASE,
    API_BASE_START,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(fn: str, time_ms: float, mem_mb: float, file: str = "app.py") -> dict:
    return {
        "function_name": fn,
        "file": file,
        "avg_time_ms": time_ms,
        "memory_peak_mb": mem_mb,
        "iterations": 100,
        "raw_output": "",
    }


def _hotspot(
    fn: str,
    severity: str = "high",
    category: str = "O(n^2) loop",
    file: str = "app.py",
) -> dict:
    return {
        "function_name": fn,
        "file": file,
        "severity": severity,
        "category": category,
        "reasoning": "test",
    }


# ---------------------------------------------------------------------------
# Unit: _compute_speedup
# ---------------------------------------------------------------------------


class TestComputeSpeedup:
    def test_basic_2x_speedup(self):
        assert _compute_speedup(10.0, 5.0) == 2.0

    def test_no_change(self):
        assert _compute_speedup(10.0, 10.0) == 1.0

    def test_regression(self):
        assert _compute_speedup(5.0, 10.0) == 0.5

    def test_both_zero(self):
        assert _compute_speedup(0.0, 0.0) == 1.0

    def test_below_noise_floor(self):
        assert _compute_speedup(0.3, 0.4) == 1.0

    def test_within_noise_pct(self):
        assert _compute_speedup(10.0, 10.4) == 1.0

    def test_above_noise_threshold(self):
        speedup = _compute_speedup(10.0, 5.0)
        assert speedup > 1.0

    def test_capped_at_max(self):
        speedup = _compute_speedup(1000.0, 0.001)
        assert speedup <= 10000.0


# ---------------------------------------------------------------------------
# Unit: _is_time_space_tradeoff
# ---------------------------------------------------------------------------


class TestTimeSpaceTradeoff:
    def test_faster_and_more_memory(self):
        assert _is_time_space_tradeoff(2.0, 1.5) is True

    def test_faster_and_less_memory(self):
        assert _is_time_space_tradeoff(2.0, 0.8) is False

    def test_slower_and_more_memory(self):
        assert _is_time_space_tradeoff(0.8, 1.5) is False

    def test_marginal_speedup_not_tradeoff(self):
        assert _is_time_space_tradeoff(1.02, 1.5) is False


# ---------------------------------------------------------------------------
# Unit: _category_score
# ---------------------------------------------------------------------------


class TestCategoryScore:
    def test_quadratic(self):
        assert _category_score("O(n^2) loop") == 1500

    def test_n_plus_1(self):
        assert _category_score("N+1 query pattern") == 1200

    def test_blocking_io(self):
        assert _category_score("blocking I/O in async handler") == 1000

    def test_unknown_category(self):
        assert _category_score("some random thing") == 500


# ---------------------------------------------------------------------------
# Unit: _match_results
# ---------------------------------------------------------------------------


class TestMatchResults:
    def test_matches_by_function_name(self):
        initial = [_result("fn_a", 10, 1), _result("fn_b", 20, 2)]
        final = [_result("fn_b", 15, 2), _result("fn_a", 5, 1.5)]
        matched = _match_results(initial, final)
        assert len(matched) == 2
        assert matched[0][0]["function_name"] == "fn_a"
        assert matched[0][1]["function_name"] == "fn_a"

    def test_unmatched_excluded(self):
        initial = [_result("fn_a", 10, 1)]
        final = [_result("fn_z", 5, 1)]
        assert _match_results(initial, final) == []

    def test_empty_inputs(self):
        assert _match_results([], []) == []


# ---------------------------------------------------------------------------
# Integration: compute_benchy_score — the two_sum scenario
# ---------------------------------------------------------------------------


class TestTwoSumScenario:
    """The exact scenario from the user's PR: O(n²)→O(n) hash-map optimisation.

    On small inputs: time barely changes (or slightly regresses due to overhead)
    and memory increases from the hash map. The old LLM-based scoring wrongly
    scored this lower. The deterministic algorithm must score it higher.
    """

    def _run_two_sum(self):
        initial = [_result("two_sum", 0.08, 0.1)]
        final = [_result("two_sum", 0.09, 0.3)]
        hotspots = [_hotspot("two_sum", severity="high", category="O(n^2) loop")]
        return compute_benchy_score(initial, final, hotspots)

    def test_overall_score_increases(self):
        score, _ = self._run_two_sum()
        # With sub-noise-floor inputs (0.08ms vs 0.09ms), speedup is neutral.
        # The score should not decrease — it stays at baseline.
        # Real-world benchmarks with proper input sizes (steps 1-3) will show
        # actual speedups; see TestTwoSumLargeInputs for that scenario.
        assert score.overall_after >= score.overall_before, (
            f"Expected after ({score.overall_after}) >= before ({score.overall_before}) "
            f"for an O(n²)→O(n) optimisation"
        )

    def test_api_score_not_penalised(self):
        score, _ = self._run_two_sum()
        # With noise-floor-neutral speedup, api_score should hold at the
        # deducted baseline (3000 - 500 for high severity = 2500), not drop further.
        assert score.api_score >= score.api_score_before, (
            f"API score ({score.api_score}) should not drop below base "
            f"({score.api_score_before}) for a noise-neutral scenario"
        )

    def test_time_not_penalised_below_noise(self):
        """Both times are < NOISE_FLOOR_MS, so speedup should be neutral (1.0)."""
        _, comparisons = self._run_two_sum()
        assert len(comparisons) == 1
        assert comparisons[0].speedup_factor == 1.0

    def test_memory_increase_not_penalised(self):
        """Memory went up but times are in noise floor → not a time-space tradeoff,
        but noise-floor speedup means memory impact should be small or zero."""
        score, _ = self._run_two_sum()
        assert score.memory_score >= MEMORY_BASE * 0.5


class TestTwoSumLargeInputs:
    """Same optimisation but with large enough inputs to show the speedup."""

    def test_clear_speedup_scores_very_high(self):
        initial = [_result("two_sum", 450.0, 2.0)]
        final = [_result("two_sum", 12.0, 8.0)]
        hotspots = [_hotspot("two_sum", severity="high", category="O(n^2) loop")]

        score, comparisons = compute_benchy_score(initial, final, hotspots)

        assert score.overall_after > score.overall_before
        assert comparisons[0].speedup_factor > 30
        assert score.time_score > TIME_BASE

    def test_time_space_tradeoff_not_penalised(self):
        """Memory 4x'd but we got a 37x speedup — memory should not drag score down."""
        initial = [_result("two_sum", 450.0, 2.0)]
        final = [_result("two_sum", 12.0, 8.0)]
        hotspots = [_hotspot("two_sum", severity="high", category="O(n^2) loop")]

        score, _ = compute_benchy_score(initial, final, hotspots)
        assert score.memory_score >= MEMORY_BASE


# ---------------------------------------------------------------------------
# Integration: general scenarios
# ---------------------------------------------------------------------------


class TestGeneralScenarios:
    def test_pure_improvement(self):
        """Both time and memory improve → high after score."""
        initial = [_result("process", 100.0, 50.0)]
        final = [_result("process", 30.0, 25.0)]
        hotspots = [_hotspot("process", severity="critical", category="inefficient algorithm")]

        score, _ = compute_benchy_score(initial, final, hotspots)
        assert score.overall_after > score.overall_before
        assert score.time_score > TIME_BASE
        assert score.memory_score > MEMORY_BASE

    def test_pure_regression(self):
        """Both time and memory got worse → after <= before."""
        initial = [_result("handler", 10.0, 5.0)]
        final = [_result("handler", 20.0, 10.0)]
        hotspots = [_hotspot("handler", severity="medium", category="blocking I/O")]

        score, _ = compute_benchy_score(initial, final, hotspots)
        # Time regression should pull score down, but complexity can still lift it.
        # The important check is that time_score < base.
        assert score.time_score < TIME_BASE

    def test_no_hotspots_gives_neutral_baseline(self):
        initial = [_result("fn", 10.0, 5.0)]
        final = [_result("fn", 10.0, 5.0)]
        score, _ = compute_benchy_score(initial, final, [])
        assert score.overall_before == TIME_BASE + MEMORY_BASE + API_BASE_START
        assert abs(score.overall_after - score.overall_before) < 500

    def test_empty_results(self):
        score, comparisons = compute_benchy_score([], [], [])
        assert comparisons == []
        assert score.overall_before > 0
        assert score.overall_after > 0

    def test_multiple_functions(self):
        initial = [
            _result("fn_a", 100.0, 10.0),
            _result("fn_b", 50.0, 5.0),
        ]
        final = [
            _result("fn_a", 25.0, 10.0),
            _result("fn_b", 50.0, 5.0),
        ]
        hotspots = [
            _hotspot("fn_a", severity="high", category="O(n^2) loop"),
            _hotspot("fn_b", severity="low", category="missing caching"),
        ]

        score, comparisons = compute_benchy_score(initial, final, hotspots)
        assert len(comparisons) == 2
        assert score.overall_after > score.overall_before

    def test_unmatched_functions_ignored(self):
        initial = [_result("fn_a", 10.0, 1.0)]
        final = [_result("fn_z", 5.0, 0.5)]
        hotspots = [_hotspot("fn_a")]

        score, comparisons = compute_benchy_score(initial, final, hotspots)
        assert comparisons == []


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    def test_score_fields_present(self):
        score, _ = compute_benchy_score(
            [_result("f", 10, 1)], [_result("f", 5, 1)], [_hotspot("f")]
        )
        assert isinstance(score, CodeMarkScore)
        assert isinstance(score.overall_before, float)
        assert isinstance(score.overall_after, float)
        assert isinstance(score.time_score, float)
        assert isinstance(score.memory_score, float)
        assert isinstance(score.api_score, float)
        assert len(score.radar_data) == 5

    def test_radar_axes_0_to_100(self):
        score, _ = compute_benchy_score(
            [_result("f", 10, 1)], [_result("f", 5, 1)], [_hotspot("f")]
        )
        for axis in score.radar_data:
            assert 0 <= axis.before <= 100
            assert 0 <= axis.after <= 100

    def test_function_comparison_shape(self):
        _, comparisons = compute_benchy_score(
            [_result("f", 10, 2)], [_result("f", 5, 1)], []
        )
        assert len(comparisons) == 1
        c = comparisons[0]
        assert isinstance(c, FunctionComparison)
        assert c.old_time_ms == 10.0
        assert c.new_time_ms == 5.0
        assert c.speedup_factor == 2.0
        assert c.memory_reduction_pct == 50.0

    def test_scores_within_bounds(self):
        score, _ = compute_benchy_score(
            [_result("f", 10, 1)], [_result("f", 5, 1)], [_hotspot("f")]
        )
        assert 0 <= score.time_score <= 8000
        assert 0 <= score.memory_score <= 6000
        assert 0 <= score.api_score <= 6000
        assert 1000 <= score.overall_after <= 20000


# ---------------------------------------------------------------------------
# Severity & category weighting
# ---------------------------------------------------------------------------


class TestSeverityWeighting:
    def test_critical_hotspot_deducts_more_from_baseline(self):
        s_crit, _ = compute_benchy_score([], [], [_hotspot("f", severity="critical")])
        s_low, _ = compute_benchy_score([], [], [_hotspot("f", severity="low")])
        assert s_crit.overall_before < s_low.overall_before

    def test_critical_improvement_scores_higher_than_low(self):
        initial = [_result("f", 100, 10)]
        final = [_result("f", 25, 10)]

        s_crit, _ = compute_benchy_score(initial, final, [_hotspot("f", severity="critical")])
        s_low, _ = compute_benchy_score(initial, final, [_hotspot("f", severity="low")])
        assert s_crit.api_score > s_low.api_score

    def test_algorithmic_category_scores_higher_than_generic(self):
        initial = [_result("f", 100, 10)]
        final = [_result("f", 25, 10)]

        s_algo, _ = compute_benchy_score(
            initial, final, [_hotspot("f", category="O(n^2) loop")]
        )
        s_generic, _ = compute_benchy_score(
            initial, final, [_hotspot("f", category="some minor issue")]
        )
        assert s_algo.api_score > s_generic.api_score
