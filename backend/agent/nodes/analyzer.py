import asyncio
import json

import structlog

from agent.schemas import AnalysisResult
from agent.state import AgentState
from services.gemini_service import GEMINI_PRO, get_agent, run_agent_logged
from services.github_service import get_file_tree, read_file
from services.parser_service import parse_repo

log = structlog.get_logger()

ANALYSIS_PROMPT = """You are a senior performance engineer. You are given:
1. An AST map of a codebase (functions, classes, imports, call edges)
2. The source code of key files

Your job is to identify performance bottlenecks. Look for:
- N+1 query patterns
- Blocking I/O in async code
- O(n^2) or worse algorithms
- Unnecessary repeated computation
- Missing caching opportunities
- Synchronous API calls that could be batched
- Large memory allocations in loops

Return a structured analysis with specific hotspots, their severity, and reasoning."""


async def parse_ast_node(state: AgentState) -> dict:
    """Extract AST data from the repository using tree-sitter."""
    repo_path = state.get("repo_path", "")
    file_tree = get_file_tree(repo_path)

    log.info("parse_ast_start", num_files=len(file_tree), files_sample=file_tree[:10])
    ast_data = await asyncio.to_thread(parse_repo, repo_path, file_tree)

    log.info(
        "parse_ast_complete",
        functions=len(ast_data.functions),
        classes=len(ast_data.classes),
        imports=len(ast_data.imports),
        call_edges=len(ast_data.call_edges),
    )

    return {
        **state,
        "file_tree": file_tree,
        "ast_map": ast_data.model_dump(),
        "messages": state.get("messages", []) + [
            f"Parsed {len(ast_data.functions)} functions, {len(ast_data.classes)} classes across {len(file_tree)} files"
        ],
    }


async def analyze_node(state: AgentState) -> dict:
    """Use Gemini to analyze the AST map and identify performance bottlenecks."""
    ast_map = state.get("ast_map", {})
    repo_path = state.get("repo_path", "")
    file_tree = state.get("file_tree", [])

    key_files = {}
    for f in file_tree[:20]:
        try:
            content = read_file(repo_path, f)
            if len(content) < 10000:
                key_files[f] = content
        except Exception:
            pass

    log.info("analyze_start", num_key_files=len(key_files), key_files=list(key_files.keys()))

    agent = get_agent(AnalysisResult, ANALYSIS_PROMPT, GEMINI_PRO)

    user_prompt = f"""## AST Map
```json
{json.dumps(ast_map, indent=2)[:8000]}
```

## Source Files
"""
    for path, content in list(key_files.items())[:10]:
        user_prompt += f"\n### {path}\n```\n{content[:3000]}\n```\n"

    result = await run_agent_logged(agent, user_prompt, node_name="analyze")
    analysis: AnalysisResult = result.output  # type: ignore[assignment]

    for hotspot in analysis.hotspots:
        log.info(
            "hotspot_found",
            function=hotspot.function_name,
            file=hotspot.file,
            severity=hotspot.severity,
            category=hotspot.category,
            reasoning=hotspot.reasoning[:150],
        )

    log.info("analyze_complete", language=analysis.language, hotspots=len(analysis.hotspots))

    return {
        **state,
        "analysis": analysis.model_dump(),
        "messages": state.get("messages", []) + [
            f"Identified {len(analysis.hotspots)} potential bottlenecks"
        ],
    }
