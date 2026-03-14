import asyncio
import json

import structlog
from pydantic import BaseModel, Field

from agent.schemas import OptimizationChange
from agent.state import AgentState
from services.gemini_service import GEMINI_FLASH, get_agent, run_agent_logged

log = structlog.get_logger()

REVIEWER_PROMPT = """You are a senior code reviewer specializing in performance optimization.
You are the CRITIC in an actor-critic optimization pipeline.

Your job is to review proposed code changes and decide whether each one is SAFE to apply.
You must reject changes that:

1. **Break correctness**: Changes that alter the function's observable behavior (different
   return values, different side effects, different error handling).
2. **Are destructive**: Changes that gut or trivialize a function (replacing the body with
   a no-op, returning a constant, removing error handling).
3. **Introduce bugs**: Off-by-one errors, null pointer risks, race conditions, missing
   awaits in async code, or incorrect type coercions.
4. **Are cosmetic only**: Changes that just rename variables, reformat code, or add/remove
   comments without any algorithmic or structural improvement.
5. **Have incorrect complexity claims**: If the explanation claims O(n) but the code is
   still O(n^2), reject it.

For each change, provide:
- `approved`: whether the change is safe to apply
- `reason`: a short explanation of why you approved or rejected it
- `suggestion`: if rejected, what the optimizer should do differently

Be strict. It is better to reject a questionable optimization than to let a bug through."""


class ChangeReview(BaseModel):
    function_name: str
    file: str
    approved: bool
    reason: str
    suggestion: str = ""


class ReviewResult(BaseModel):
    reviews: list[ChangeReview]
    summary: str = Field(description="One-sentence overall assessment")


REVIEW_TIMEOUT_S = 45


async def review_optimization(
    changes: list[OptimizationChange],
    file_content: str,
    file_path: str,
) -> list[ChangeReview]:
    """Review a list of optimization changes using a critic LLM.

    Returns a list of per-change reviews. On timeout or failure, all changes
    are approved by default (fail-open) so the pipeline isn't blocked.
    """
    if not changes:
        return []

    agent = get_agent(ReviewResult, REVIEWER_PROMPT, GEMINI_FLASH)

    changes_payload = [
        {
            "function_name": c.function_name,
            "file": c.file,
            "original_snippet": c.original_snippet[:2000],
            "optimized_snippet": c.optimized_snippet[:2000],
            "explanation": c.explanation,
            "expected_improvement": c.expected_improvement,
        }
        for c in changes
    ]

    prompt = f"""## File: {file_path}

## Source Code (current)
```
{file_content[:6000]}
```

## Proposed Optimization Changes
```json
{json.dumps(changes_payload, indent=2)}
```

Review each change. Be strict about correctness but pragmatic about style."""

    try:
        result = await asyncio.wait_for(
            run_agent_logged(agent, prompt, node_name=f"review_{file_path.split('/')[-1]}"),
            timeout=REVIEW_TIMEOUT_S,
        )
        review: ReviewResult = result.output  # type: ignore[assignment]

        for r in review.reviews:
            log.info(
                "review_result",
                function=r.function_name,
                approved=r.approved,
                reason=r.reason[:200],
            )

        return review.reviews
    except TimeoutError:
        log.warning("review_timeout", file=file_path, timeout_s=REVIEW_TIMEOUT_S)
    except Exception as e:
        log.warning("review_failed", file=file_path, error=str(e))

    return [
        ChangeReview(
            function_name=c.function_name,
            file=c.file,
            approved=True,
            reason="Review skipped (timeout/error) — approved by default",
        )
        for c in changes
    ]
