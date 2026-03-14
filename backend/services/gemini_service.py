import structlog
from google.genai.types import ThinkingLevel
from pydantic_ai import Agent, AgentRunResult
from pydantic_ai.models.google import GoogleModelSettings

log = structlog.get_logger()

GEMINI_PRO = "google-gla:gemini-3.1-pro-preview"
GEMINI_FLASH = "google-gla:gemini-3-flash-preview"

PRO_SETTINGS = GoogleModelSettings(
    google_thinking_config={"thinking_level": ThinkingLevel.LOW},
)

def get_agent(output_type: type, system_prompt: str, model: str = GEMINI_PRO) -> Agent:
    """Create a PydanticAI agent configured for the given output schema."""
    agent = Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
    )
    agent._model_str = model  # type: ignore[attr-defined]
    log.debug(
        "agent_created",
        model=model,
        is_pro=model == GEMINI_PRO,
        output_type=output_type.__name__,
    )
    return agent


async def run_agent_logged(
    agent: Agent,
    prompt: str,
    *,
    node_name: str = "unknown",
    model_settings: GoogleModelSettings | None = None,
) -> AgentRunResult:
    """Run a PydanticAI agent with detailed logging of inputs and outputs."""
    output_type_name = getattr(agent, '_output_type', agent).__class__.__name__
    model_str = getattr(agent, '_model_str', '')
    model_name = model_str or str(getattr(agent, 'model', 'unknown'))

    # Default to PRO_SETTINGS for Pro model calls
    settings = model_settings
    if settings is None and model_str == GEMINI_PRO:
        settings = PRO_SETTINGS

    thinking_config = getattr(settings, "google_thinking_config", None) if settings else None
    thinking_level = thinking_config.get("thinking_level") if thinking_config else None

    log.info(
        "gemini_request",
        node=node_name,
        model=model_name,
        output_type=output_type_name,
        prompt_chars=len(prompt),
        prompt_preview=prompt[:300].replace("\n", " "),
        is_pro=model_str == GEMINI_PRO,
        settings_applied=settings is not None,
        settings_repr=repr(settings),
        thinking_config=repr(thinking_config),
        thinking_level=repr(thinking_level),
    )

    try:
        result = await agent.run(prompt, model_settings=settings)
    except Exception as e:
        log.error(
            "gemini_request_failed",
            node=node_name,
            model=model_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise

    output = result.output
    output_preview = str(output)[:500]

    log.info(
        "gemini_response",
        node=node_name,
        model=model_name,
        output_type=type(output).__name__,
        output_preview=output_preview,
    )

    return result
