import json
import time

import structlog
from pydantic import BaseModel
from pydantic_ai import Agent, AgentRunResult

from services.log_utils import log_block

log = structlog.get_logger()

GEMINI_PRO = "google-gla:gemini-2.5-pro"
GEMINI_FLASH = "google-gla:gemini-2.0-flash"


def _output_type_label(output_type: type) -> str:
    name = getattr(output_type, "__name__", None)
    return name if name else str(output_type)


def get_agent(output_type: type, system_prompt: str, model: str = GEMINI_PRO) -> Agent:
    """Create a PydanticAI agent configured for the given output schema."""
    agent = Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
    )
    agent._codemark_system_prompt = system_prompt  # type: ignore[attr-defined]
    agent._codemark_output_type = _output_type_label(output_type)  # type: ignore[attr-defined]
    return agent


def _format_output(output: object) -> str:
    """Serialize a Gemini response for logging."""
    if isinstance(output, BaseModel):
        return json.dumps(output.model_dump(), indent=2, default=str)
    if isinstance(output, list):
        items = []
        for item in output:
            if isinstance(item, BaseModel):
                items.append(item.model_dump())
            else:
                items.append(item)
        return json.dumps(items, indent=2, default=str)
    return str(output)


async def run_agent_logged(
    agent: Agent,
    prompt: str,
    *,
    node_name: str = "unknown",
) -> AgentRunResult:
    """Run a PydanticAI agent with detailed logging of inputs and outputs."""
    model_name = str(getattr(agent, "model", "unknown"))
    system_prompt = getattr(agent, "_codemark_system_prompt", "<unavailable>")
    output_type = getattr(agent, "_codemark_output_type", "unknown")

    log_block(
        f"GEMINI PROMPT [{node_name}]",
        metadata={
            "model": model_name,
            "output_type": output_type,
            "prompt_chars": len(prompt),
        },
        sections={
            "SYSTEM PROMPT": system_prompt,
            "USER PROMPT": prompt,
        },
        color="blue",
    )

    start = time.monotonic()
    try:
        result = await agent.run(prompt)
    except Exception as e:
        elapsed = time.monotonic() - start
        log_block(
            f"GEMINI ERROR [{node_name}]",
            metadata={
                "model": model_name,
                "error_type": type(e).__name__,
                "elapsed_s": round(elapsed, 2),
            },
            sections={"ERROR": str(e)},
            color="red",
        )
        raise

    elapsed = time.monotonic() - start
    output = result.output
    formatted = _format_output(output)

    log_block(
        f"GEMINI RESPONSE [{node_name}]",
        metadata={
            "model": model_name,
            "output_type": type(output).__name__,
            "elapsed_s": round(elapsed, 2),
            "response_chars": len(formatted),
        },
        sections={"RESPONSE": formatted},
        color="green",
    )

    return result
