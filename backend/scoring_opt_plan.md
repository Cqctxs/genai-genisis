## Plan: Enhance Benchmark Reliability and Accuracy

Improve the AI-generated benchmarking scripts so they reliably capture profound algorithmic and architectural optimizations without crashing or timing out due to unrealistic synthetic data shapes or aggressive system timeouts. 

**Steps**
1. **Un-Uniform Mock Data Generation**
   Update the benchmark generation prompt to ensure mock data has high variance (using seeded randomness or modulo algorithms). Currently, engines like V8 and Python aggressively optimize uniform arrays of identical data, artificially hiding real-world memory access and operational overheads across various algorithmic approaches.
2. **Mathematical Target-Based Dynamic Iterations**
   Replace the hardcoded iteration cliff steps with a dynamic math target. The script should explicitly target a safe total time (e.g., 3-5 seconds):
   `iterations = Math.max(5, Math.floor(4000 / single_call_ms))`
3. **Complexity-Aware Max Input Bounds**
   Change the input size logic to be generally adaptive. Linear or constant time functions can tolerate massive datasets (e.g., `N=50,000`), but for quadratic or worse algorithmic patterns, bounds must be strictly enforced (e.g., `N < 1000`) before generation, ensuring the scripts don't chronically breach the 15s timeout before iterations even begin.
4. **Fingerprint Overhead Reduction**
   Update the prompt to explicitly truncate or deterministically sample the fingerprint logic. Serializing returning objects to a JSON string takes massive blocking CPU time, which independently causes valid optimizations to fail the 15s timeout limit constraint. Instruct the LLM to slice or truncate massive outputs before serializing. 
5. **Adjust Prompt Timeout Constants**
   Fix the `25 seconds` wording in `BENCHMARK_PROMPT` down to `Ensure total estimated runtime stays heavily under 10 seconds` so it safely aligns with Modal's hard 15-second cap.
6. **Un-Cap Formula Score Limits**
   In `scoring_service.py`, `MAX_SPEEDUP_CAP` is heavily capped at 100x. When moving between vastly different algorithmic paradigms, real large dataset speedups can exceed 1000x or more. Lift the arbitrary ceiling values across `MAX_SPEEDUP_CAP`, `time_delta`, and API logic. Use a more permissive logarithmic growth instead of strict truncation.

**Relevant files**
- [backend/agent/nodes/benchmarker.py](backend/agent/nodes/benchmarker.py) — Edit the `BENCHMARK_PROMPT` to enforce these new constraints precisely.
- [backend/services/scoring_service.py](backend/services/scoring_service.py) — Un-cap formula constraints.

**Verification**
1. Run a benchmarker trial on a notoriously slow, highly-complex function that returns a massive object.
2. Verify total execution runs cleanly in `~3s`, handles fingerprinting instantly without breaking, and accurately yields high single-run `ms` figures that successfully drop proportionally post-optimization without hitting artificial ceilings.