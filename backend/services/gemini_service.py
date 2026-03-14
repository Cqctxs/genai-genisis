import json
import time

import structlog
from pydantic import BaseModel
from google.genai.types import ThinkingLevel
from pydantic_ai import Agent, AgentRunResult

from services.log_utils import log_block
from pydantic_ai.models.google import GoogleModelSettings

log = structlog.get_logger()

GEMINI_PRO = "google-gla:gemini-3.1-pro-preview"
GEMINI_FLASH = "google-gla:gemini-3-flash-preview"


def _output_type_label(output_type: type) -> str:
    name = getattr(output_type, "__name__", None)
    return name if name else str(output_type)

PRO_SETTINGS = GoogleModelSettings(
    google_thinking_config={"thinking_level": ThinkingLevel.LOW},
)

PRO_SETTINGS_MEDIUM = GoogleModelSettings(
    google_thinking_config={"thinking_level": ThinkingLevel.MEDIUM},
)

def get_agent(output_type: type, system_prompt: str, model: str = GEMINI_PRO) -> Agent:
    """Create a PydanticAI agent configured for the given output schema."""
    agent = Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
    )
    agent._codemark_system_prompt = system_prompt  # type: ignore[attr-defined]
    agent._codemark_output_type = _output_type_label(output_type)  # type: ignore[attr-defined]
    agent._model_str = model  # type: ignore[attr-defined]
    log.debug(
        "agent_created",
        model=model,
        is_pro=model == GEMINI_PRO,
        output_type=_output_type_label(output_type),
    )
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
    model_settings: GoogleModelSettings | None = None,
) -> AgentRunResult:
    """Run a PydanticAI agent with detailed logging of inputs and outputs."""
    system_prompt = getattr(agent, "_codemark_system_prompt", "<unavailable>")
    model_str = getattr(agent, '_model_str', 'unknown')
    output_type = getattr(agent, "_codemark_output_type", "unknown")

    # Default to PRO_SETTINGS for Pro model calls
    settings = model_settings
    if settings is None and model_str == GEMINI_PRO:
        settings = PRO_SETTINGS

    thinking_config = getattr(settings, "google_thinking_config", None) if settings else None
    thinking_level = thinking_config.get("thinking_level") if thinking_config else None

    log_block(
        f"GEMINI REQUEST [{node_name}]",
        metadata={
            "model": model_str,
            "output_type": output_type,
            "prompt_chars": len(prompt),
            "is_pro": model_str == GEMINI_PRO,
            "thinking_level": repr(thinking_level),
        },
        sections={
            "SYSTEM PROMPT": system_prompt,
            "USER PROMPT": prompt,
        },
        color="blue",
    )

    start = time.monotonic()
    try:
        result = await agent.run(prompt, model_settings=settings)
    except Exception as e:
        elapsed = time.monotonic() - start
        log_block(
            f"GEMINI ERROR [{node_name}]",
            metadata={
                "model": model_str,
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
            "model": model_str,
            "output_type": type(output).__name__,
            "elapsed_s": round(elapsed, 2),
            "response_chars": len(formatted),
        },
        sections={"RESPONSE": formatted},
        color="green",
        max_section_chars=1000,
    )

    return result
