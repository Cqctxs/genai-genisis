import asyncio
import sys
import os
import json
from pathlib import Path

# Add project root and backend to sys.path so we can import backend modules
current_dir = Path(__file__).parent.absolute()
project_root = current_dir.parent.absolute()
backend_dir = project_root / "backend"

sys.path.insert(0, str(project_root))
sys.path.insert(0, str(backend_dir))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolRequest

try:
    from backend.agent.graph import _run_local_pipeline
except ImportError as e:
    print(f"Warning: Failed to import backend modules: {e}", file=sys.stderr)

app = Server("benchy-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List the available tools."""
    return [
        Tool(
            name="analyze_local_code",
            description="Run the full end-to-end optimization pipeline on local code files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "object",
                        "description": "A dictionary mapping file paths to their string contents.",
                    },
                    "language": {
                        "type": "string",
                        "description": "The primary language of the code (e.g. 'python', 'javascript/typescript').",
                    },
                    "optimization_bias": {
                        "type": "string",
                        "description": "Bias for optimization ('balanced', 'speed', 'memory'). Default is 'balanced'.",
                        "default": "balanced",
                    },
                },
                "required": ["files", "language"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool execution."""
    if name == "analyze_local_code":
        files = arguments.get("files", {})
        language = arguments.get("language", "python")
        bias = arguments.get("optimization_bias", "balanced")

        try:
            # Execute the backend pipeline
            result = await _run_local_pipeline(
                files=files, language=language, optimization_bias=bias, broadcast=None
            )
            # Return the resulting dictionary as a JSON string
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error analyzing code: {str(e)}")]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
