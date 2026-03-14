import structlog
from pydantic_ai import Agent, AgentRunResult

log = structlog.get_logger()

GEMINI_PRO = "google-gla:gemini-2.5-pro"
GEMINI_FLASH = "google-gla:gemini-2.0-flash"


def get_agent(output_type: type, system_prompt: str, model: str = GEMINI_PRO) -> Agent:
    """Create a PydanticAI agent configured for the given output schema."""
    return Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
    )


async def run_agent_logged(
    agent: Agent,
    prompt: str,
    *,
    node_name: str = "unknown",
) -> AgentRunResult:
    """Run a PydanticAI agent with detailed logging of inputs and outputs."""
    output_type_name = getattr(agent, '_output_type', agent).__class__.__name__
    model_name = str(getattr(agent, 'model', 'unknown'))

    log.info(
        "gemini_request",
        node=node_name,
        model=model_name,
        output_type=output_type_name,
        prompt_chars=len(prompt),
        prompt_preview=prompt[:300].replace("\n", " "),
    )

    try:
        result = await agent.run(prompt)
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
