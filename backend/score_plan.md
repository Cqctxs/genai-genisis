# Runtime Performance Metric Plan

## 1. Problem Description
Currently, the UI dashboard calculates overall evaluation metrics using **raw execution time aggregation** (`totalOldTime` vs `totalNewTime`). This creates an imbalance where a single slow, unoptimized function will completely dominate the total runtime metric shown to the user. For instance, an improvement from 10ms to 1ms (10x speedup) on one function is visually erased if another function runs at 10,000ms. 

The requirement is to implement a different metric to display **ONLY for the runtime performance**, ignoring the overall `benchy_score` calculation.

## 2. Intended Solution
Instead of summing absolute execution time, the total runtime performance metric should use the **Geometric Mean of Relative Speedups**. 

- **Relative Speedup:** Each function already has a `speedup_factor` calculated (e.g., a function improving from 10ms to 1ms has a factor of 10.0).
- **Geometric Mean:** We will calculate the geometric mean of all the `speedup_factor` values. This ensures that a massive 10x improvement on a small function is mathematically balanced against a 1.2x improvement on a larger function, reflecting the true overall effort of the optimizations.

---

## 3. Step-by-Step Implementation Plan

### Step 1: Frontend Calculation Update
In `frontend/src/components/score-dashboard.tsx`, locate the section where `totalOldTime` and `totalNewTime` are calculated using `reduce()`.
- Remove the `totalOldTime` and `totalNewTime` calculations.
- Introduce a new calculation for the geometric mean speedup using the `functions` array:
  ```javascript
  const speedups = functions.map(f => Math.max(f.speedup_factor, 0.01)); // prevent log(0)
  const geomeanSpeedup = speedups.length > 0 
    ? Math.exp(speedups.reduce((acc, val) => acc + Math.log(val), 0) / speedups.length) 
    : 1;
  ```

### Step 2: Refactor the Dashboard UI
Still in `frontend/src/components/score-dashboard.tsx`:
- Find the metric card displaying **"Total Execution Time"**.
- Change the header label from "Total Execution Time" to **"Overall Speedup"**.
- Replace the animated absolute millisecond values (`<AnimatedScore>`) with the newly calculated `geomeanSpeedup`. 
- Change the unit from `ms` to `x` (e.g., resulting in "3.1x").
- Ensure that the conditional color coding reflects this: if `geomeanSpeedup > 1.05`, it's positive (green/blue); if it's `< 1.0`, it's a regression (red); else neutral.

### Step 3: Clean up redundant absolute time data
In `backend/agent/nodes/reporter.py`, the backend logs and currently aggregates total absolute execution time strings in the `report_start` log context.
- Keep the absolute `time_ms` for individual per-function metrics (`FunctionComparison` objects), as granular data is still useful for table views, but remove any UI text asserting "Saved X ms total".

### Step 4: Validate Changes
- Ensure that the new **Overall Speedup** multiplier accurately reflects when a small function completes a large relative optimization while a large function sits neutral.
- A quick frontend test (or simulated react prop data) should confirm that `speedup_factor: 10` and `speedup_factor: 1` yield an overall score of `~3.16x`, independent of their absolute millisecond runtimes.
- Run UI visually to ensure the "Overall Speedup" text isn't overflowing or badly formatted compared to the previous `ms` display.

---

## 5. Implementation Changelog

### Step 1: Frontend Calculation Update — DONE
**File:** `frontend/src/components/score-dashboard.tsx`
- Removed `totalOldTime` and `totalNewTime` variables (raw time aggregation via `reduce()`).
- Removed `avgSpeedup` (arithmetic mean of speedup factors).
- Added `speedups` array using `Math.max(f.speedup_factor, 0.01)` to prevent `log(0)`.
- Added `geomeanSpeedup` calculation using `Math.exp(Σ log(speedup) / n)` — the geometric mean of per-function relative speedups.

### Step 2: Dashboard UI Refactor — DONE
**File:** `frontend/src/components/score-dashboard.tsx`
- **Hero card:** Replaced the "Total Execution Time" before→after display (showing absolute ms values) with a single "Overall Speedup" hero metric showing the geometric mean as `Nx`.
- **Color coding:** The hero metric uses conditional coloring — green if `≥1.05x`, red if `<1.0x`, neutral otherwise.
- **Subtitle:** Added descriptive text "Geometric mean of per-function speedups" under the hero value.
- **Metric cards:** Replaced the "Execution Time" card (absolute ms before/after) with an "Overall Speedup" card showing the geometric mean. Removed the redundant "Avg Speedup" card (was arithmetic mean). Kept the "Memory Peak" card unchanged.

### Step 3: Backend Cleanup — NO CHANGES NEEDED
**File:** `backend/agent/nodes/reporter.py`
- Reviewed the file. The `report_start` log includes `initial_total_ms` and `final_total_ms`, but these are internal structlog entries for backend debugging, not user-facing text.
- The `_fallback_summary` template does not contain "Saved X ms total" or any aggregated absolute time assertion.
- **Decision:** No backend changes made — removing debug logs would reduce observability with no user benefit. The plan's intent (removing user-facing absolute time aggregation) was fully addressed by the frontend changes in Steps 1-2.

### Step 4: Validation — PASSED
- `next build` compiles with **zero TypeScript errors**.
- Geometric mean math verified: `geomean([10, 1]) = 3.1623` (matches expected `√10 ≈ 3.16`).
- No dangling references to removed variables (`totalOldTime`, `totalNewTime`, `avgSpeedup`) remain in the codebase.