from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    repo_url: str
    repo_path: str
    github_token: str
    optimization_bias: str
    fast_mode: bool
    file_tree: list[str]
    ast_map: dict[str, Any]
    analysis: dict[str, Any]
    benchmark_code: list[dict[str, Any]]
    initial_results: list[dict[str, Any]]
    graph_data: dict[str, Any]
    optimized_files: dict[str, str]
    original_files: dict[str, str]
    final_results: list[dict[str, Any]]
    triage_result: dict[str, Any]
    comparison: dict[str, Any]
    correctness_failures: list[dict[str, Any]]
    benchmark_details: list[dict[str, Any]]
    pr_url: str
    messages: list[str]
    error: str | None
    retry_count: int
