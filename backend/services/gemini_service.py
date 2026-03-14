import os

import structlog
from pydantic_ai import Agent

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
