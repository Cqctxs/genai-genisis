"""Formatted block logging for high-signal events (Gemini calls, Modal calls).

Produces banner-style output that is visually distinct from normal structlog
lines, making prompts, responses, and benchmark scripts easy to find in logs.
"""

import sys

HEAVY_LINE = "=" * 90
LIGHT_LINE = "─" * 90


def log_block(
    title: str,
    *,
    sections: dict[str, str] | None = None,
    metadata: dict[str, str | int | float | bool | None] | None = None,
    color: str = "blue",
) -> None:
    """Print a visually distinct log block to stderr.

    Args:
        title: Banner heading (e.g. "GEMINI PROMPT [analyze]").
        sections: Named text blocks to print (e.g. {"SYSTEM PROMPT": "...", "USER PROMPT": "..."}).
        metadata: Key-value pairs shown as a compact header below the banner.
        color: ANSI color name for the banner — "blue", "green", "yellow", "magenta", "cyan".
    """
    ansi = {
        "blue": "\033[94m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "red": "\033[91m",
    }
    c = ansi.get(color, "")
    reset = "\033[0m" if c else ""
    dim = "\033[2m"

    header = f" {title} "
    lines = [
        "",
        f"{c}{HEAVY_LINE}{reset}",
        f"{c}{header:=^90}{reset}",
        f"{c}{HEAVY_LINE}{reset}",
    ]

    if metadata:
        for key, value in metadata.items():
            lines.append(f"  {dim}{key}:{reset} {value}")

    if sections:
        for section_title, content in sections.items():
            section_header = f" {section_title} "
            lines.append(f"{dim}{section_header:─^90}{reset}")
            lines.append(content)

    lines.append(f"{c}{HEAVY_LINE}{reset}")
    lines.append("")

    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()
