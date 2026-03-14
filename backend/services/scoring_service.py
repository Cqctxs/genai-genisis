"""Deterministic CodeMark scoring algorithm.

Replaces the previous LLM-based scoring with a formula that correctly evaluates
algorithmic improvements, handles benchmark noise floors, and recognizes
time-space tradeoffs (e.g. hash-map optimization: O(n²)→O(n) with more memory).

Score anatomy (0–20 000):
  time_score       0–8 000  (40 % weight)
  memory_score     0–6 000  (30 % weight)
  complexity_score 0–6 000  (30 % weight)
"""

from __future__ import annotations

import math

import structlog

from agent.schemas import CodeMarkScore, FunctionComparison, RadarAxis

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

NOISE_FLOOR_MS = 0.5
NOISE_FLOOR_PCT = 0.05
MAX_SPEEDUP_CAP = 100.0

SEVERITY_DEDUCTION = {"critical": 800, "high": 500, "medium": 300, "low": 100}
SEVERITY_WEIGHT = {"critical": 1.5, "high": 1.2, "medium": 1.0, "low": 0.7}

ALGO_CATEGORY_SCORES: dict[str, int] = {
    "o(n^2)": 1500,
    "o(n²)": 1500,
    "o(n^3)": 2000,
    "o(n³)": 2000,
    "quadratic": 1500,
    "cubic": 2000,
    "exponential": 2500,
    "inefficient algorithm": 1500,
    "n+1 query": 1200,
    "n+1": 1200,
    "blocking i/o": 1000,
    "blocking io": 1000,
    "synchronous": 800,
    "repeated computation": 800,
    "missing caching": 700,
    "unnecessary": 600,
    "memory allocation": 500,
    "large memory": 500,
}

TIME_BASE = 3200
MEMORY_BASE = 2400
COMPLEXITY_BASE_START = 3000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_results(
    initial: list[dict], final: list[dict]
) -> list[tuple[dict, dict]]:
    """Pair initial/final results by (function_name, file)."""
    final_by_fn: dict[tuple[str, str], dict] = {}
    for r in final:
        fn = r.get("function_name", "")
        file_path = r.get("file", "")
        if fn and file_path:
            final_by_fn[(fn, file_path)] = r

    pairs: list[tuple[dict, dict]] = []
    for r in initial:
        fn = r.get("function_name", "")
        file_path = r.get("file", "")
        if (fn, file_path) in final_by_fn:
            pairs.append((r, final_by_fn[(fn, file_path)]))
    return pairs


def _compute_speedup(old_time: float, new_time: float) -> float:
    """Compute speedup factor with noise-floor handling.

    Returns 1.0 (neutral) when the difference is within measurement noise.
    """
    if old_time <= 0 and new_time <= 0:
        return 1.0
    if new_time <= 0:
        return min(MAX_SPEEDUP_CAP, max(old_time, 1.0))
    if old_time <= 0:
        return 1.0 / min(MAX_SPEEDUP_CAP, max(new_time, 1.0))

    if old_time < NOISE_FLOOR_MS and new_time < NOISE_FLOOR_MS:
        return 1.0

    diff = abs(old_time - new_time)
    if diff < max(NOISE_FLOOR_MS, old_time * NOISE_FLOOR_PCT):
        return 1.0

    return min(old_time / new_time, MAX_SPEEDUP_CAP)


def _is_time_space_tradeoff(speedup: float, memory_ratio: float) -> bool:
    """True when speed improved but memory grew — a deliberate tradeoff."""
    return speedup > 1.05 and memory_ratio > 1.05


def _is_noise_floor_neutral(old_time: float, new_time: float) -> bool:
    """True when both times are within the noise floor (sub-ms jitter)."""
    if old_time < NOISE_FLOOR_MS and new_time < NOISE_FLOOR_MS:
        return True
    diff = abs(old_time - new_time)
    return diff < max(NOISE_FLOOR_MS, old_time * NOISE_FLOOR_PCT)


def _fn_has_algo_hotspot(fn_name: str, hotspots: list[dict]) -> bool:
    """True if there's an algorithmic-improvement hotspot for this function."""
    for hs in hotspots:
        if hs.get("function_name", "") != fn_name:
            continue
        cat = hs.get("category", "").lower()
        for pattern in ALGO_CATEGORY_SCORES:
            if pattern in cat and ALGO_CATEGORY_SCORES[pattern] >= 1000:
                return True
    return False


def _category_score(category: str) -> int:
    """Score a hotspot category by matching known algorithmic-improvement patterns."""
    cat_lower = category.lower()
    best = 0
    for pattern, pts in ALGO_CATEGORY_SCORES.items():
        if pattern in cat_lower:
            best = max(best, pts)
    return best if best else 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_benchy_score(
    initial_results: list[dict],
    final_results: list[dict],
    hotspots: list[dict],
) -> tuple[CodeMarkScore, list[FunctionComparison]]:
    """Deterministic scoring from raw benchmark data + hotspot analysis.

    Returns (CodeMarkScore, per-function comparisons).
    """
    matched = _match_results(initial_results, final_results)

    # ------------------------------------------------------------------
    # 1. Baseline complexity score (penalised by detected hotspots)
    # ------------------------------------------------------------------
    complexity_base = COMPLEXITY_BASE_START
    for hs in hotspots:
        sev = hs.get("severity", "medium").lower()
        complexity_base -= SEVERITY_DEDUCTION.get(sev, 200)
    complexity_base = max(500, min(complexity_base, COMPLEXITY_BASE_START))

    # ------------------------------------------------------------------
    # 2. Per-function metrics
    # ------------------------------------------------------------------
    comparisons: list[FunctionComparison] = []
    speedups: list[float] = []
    mem_impacts: list[float] = []
    time_space_tradeoff_count = 0

    for init, fin in matched:
        old_t = float(init.get("avg_time_ms", 0))
        new_t = float(fin.get("avg_time_ms", 0))
        old_m = float(init.get("memory_peak_mb", 0))
        new_m = float(fin.get("memory_peak_mb", 0))
        fn_name = init.get("function_name", "")

        speedup = _compute_speedup(old_t, new_t)
        mem_ratio = (new_m / old_m) if old_m > 0 else 1.0
        mem_reduction_pct = ((old_m - new_m) / old_m * 100) if old_m > 0 else 0.0

        speedups.append(speedup)

        is_tradeoff = _is_time_space_tradeoff(speedup, mem_ratio)
        noise_neutral = _is_noise_floor_neutral(old_t, new_t)
        has_algo_hotspot = _fn_has_algo_hotspot(fn_name, hotspots)

        if is_tradeoff:
            time_space_tradeoff_count += 1
            mem_impacts.append(0.0)
        elif noise_neutral and has_algo_hotspot and mem_ratio > 1.0:
            # Timing couldn't reveal the algorithmic win on small inputs;
            # the memory increase is almost certainly a deliberate data-structure
            # tradeoff (e.g. hash-map for O(1) lookups).  Treat as neutral.
            time_space_tradeoff_count += 1
            mem_impacts.append(0.0)
        elif mem_ratio <= 1.0:
            mem_impacts.append((1.0 - mem_ratio) * 3000)
        else:
            mem_impacts.append(-(mem_ratio - 1.0) * 1000)

        comparisons.append(
            FunctionComparison(
                function_name=init.get("function_name", "unknown"),
                file=init.get("file", "unknown"),
                old_time_ms=round(old_t, 3),
                new_time_ms=round(new_t, 3),
                speedup_factor=round(speedup, 2),
                old_memory_mb=round(old_m, 3),
                new_memory_mb=round(new_m, 3),
                memory_reduction_pct=round(mem_reduction_pct, 2),
            )
        )

    # ------------------------------------------------------------------
    # 3. Time score
    # ------------------------------------------------------------------
    if speedups:
        log_sum = sum(math.log(max(s, 0.01)) for s in speedups)
        geo_mean = math.exp(log_sum / len(speedups))
        time_delta = math.log2(max(geo_mean, 0.01)) * 2500
        time_delta = max(-2000, min(time_delta, 4800))
    else:
        time_delta = 0.0

    time_score = max(0, min(TIME_BASE + time_delta, 8000))

    # ------------------------------------------------------------------
    # 4. Memory score
    # ------------------------------------------------------------------
    if mem_impacts:
        mem_delta = sum(mem_impacts) / len(mem_impacts)
        mem_delta = max(-1500, min(mem_delta, 3600))
    else:
        mem_delta = 0.0

    memory_score = max(0, min(MEMORY_BASE + mem_delta, 6000))

    # ------------------------------------------------------------------
    # 5. Complexity score (biggest lever for algorithmic improvements)
    # ------------------------------------------------------------------
    # Map function name → speedup so complexity reward can be gated on
    # whether benchmarks actually improved (or at least didn't regress).
    speedup_by_fn = {c.function_name: c.speedup_factor for c in comparisons}
    optimised_fns = {c.function_name for c in comparisons}
    complexity_delta = 0.0

    for hs in hotspots:
        fn = hs.get("function_name", "")
        if fn not in optimised_fns:
            continue

        cat_pts = _category_score(hs.get("category", ""))
        sev_mult = SEVERITY_WEIGHT.get(hs.get("severity", "medium").lower(), 1.0)
        raw_pts = cat_pts * sev_mult

        # Scale the reward by actual benchmark outcome.
        # speedup >= 1.0  → full credit
        # speedup in [0.9, 1.0) → partial credit (noise / neutral)
        # speedup < 0.9  → no complexity credit (clear regression)
        fn_speedup = speedup_by_fn.get(fn, 1.0)
        if fn_speedup >= 1.0:
            scale = 1.0
        elif fn_speedup >= 0.9:
            scale = (fn_speedup - 0.9) / 0.1  # linear 0→1 over [0.9, 1.0]
        else:
            scale = 0.0

        complexity_delta += raw_pts * scale

    complexity_delta = min(complexity_delta, 3000)
    complexity_score = max(0, min(complexity_base + complexity_delta, 6000))

    # ------------------------------------------------------------------
    # 6. Overall before / after
    # ------------------------------------------------------------------
    overall_before = TIME_BASE + MEMORY_BASE + complexity_base
    overall_after = time_score + memory_score + complexity_score
    overall_after = max(1000, min(overall_after, 20000))

    log.info(
        "benchy_score_computed",
        overall_before=round(overall_before, 1),
        overall_after=round(overall_after, 1),
        time_score=round(time_score, 1),
        memory_score=round(memory_score, 1),
        complexity_score=round(complexity_score, 1),
        time_delta=round(time_delta, 1),
        mem_delta=round(mem_delta, 1),
        complexity_delta=round(complexity_delta, 1),
        geo_mean_speedup=round(math.exp(sum(math.log(max(s, 0.01)) for s in speedups) / len(speedups)), 2) if speedups else 1.0,
        time_space_tradeoffs=time_space_tradeoff_count,
        functions_matched=len(comparisons),
    )

    # ------------------------------------------------------------------
    # 7. Radar data (normalised 0–100)
    # ------------------------------------------------------------------
    radar = _build_radar(
        comparisons, hotspots, time_delta, mem_delta, complexity_delta,
    )

    score = CodeMarkScore(
        overall_before=round(overall_before, 1),
        overall_after=round(overall_after, 1),
        time_score=round(time_score, 1),
        time_score_before=float(TIME_BASE),
        memory_score=round(memory_score, 1),
        memory_score_before=float(MEMORY_BASE),
        complexity_score=round(complexity_score, 1),
        complexity_score_before=round(complexity_base, 1),
        radar_data=radar,
    )
    return score, comparisons


# ---------------------------------------------------------------------------
# Radar chart builder
# ---------------------------------------------------------------------------

def _build_radar(
    comparisons: list[FunctionComparison],
    hotspots: list[dict],
    time_delta: float,
    mem_delta: float,
    complexity_delta: float,
) -> list[RadarAxis]:
    """Build radar axes normalised to 0–100. 50 is the neutral baseline."""

    def _clamp(v: float) -> float:
        return max(0, min(v, 100))

    avg_speedup = (
        sum(c.speedup_factor for c in comparisons) / len(comparisons)
        if comparisons else 1.0
    )

    io_before = 50.0
    io_after = _clamp(50 + (avg_speedup - 1) * 20)

    cpu_before = 50.0
    cpu_after = _clamp(50 + time_delta / 100)

    mem_before = 50.0
    mem_after = _clamp(50 + mem_delta / 60)

    concurrency_before = 50.0
    conc_cats = {"blocking i/o", "blocking io", "synchronous"}
    conc_boost = sum(
        10 for hs in hotspots
        if any(p in hs.get("category", "").lower() for p in conc_cats)
    )
    concurrency_after = _clamp(50 + conc_boost)

    quality_before = 50.0
    addressed = sum(
        1 for hs in hotspots
        if hs.get("function_name", "") in {c.function_name for c in comparisons}
    )
    total = max(len(hotspots), 1)
    quality_after = _clamp(50 + (addressed / total) * 40 + complexity_delta / 100)

    return [
        RadarAxis(axis="I/O Speed", before=round(io_before, 1), after=round(io_after, 1)),
        RadarAxis(axis="CPU Efficiency", before=round(cpu_before, 1), after=round(cpu_after, 1)),
        RadarAxis(axis="Memory Footprint", before=round(mem_before, 1), after=round(mem_after, 1)),
        RadarAxis(axis="Concurrency", before=round(concurrency_before, 1), after=round(concurrency_after, 1)),
        RadarAxis(axis="Code Quality", before=round(quality_before, 1), after=round(quality_after, 1)),
    ]
