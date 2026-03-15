from pydantic import BaseModel, Field


class FunctionInfo(BaseModel):
    file: str
    name: str
    line_start: int
    line_end: int
    params: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    parameter_types: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of parameter name to its resolved type annotation",
    )
    return_type: str = Field(
        default="",
        description="Resolved return type annotation (empty string if unknown)",
    )
    decorators: list[str] = Field(
        default_factory=list,
        description="Decorator names applied to this function (e.g. ['staticmethod', 'app.route'])",
    )
    is_async: bool = Field(
        default=False,
        description="Whether this function is declared async",
    )
    is_generator: bool = Field(
        default=False,
        description="Whether this function contains yield/yield from",
    )
    docstring: str = Field(
        default="",
        description="Leading docstring or JSDoc comment for the function",
    )


class ClassInfo(BaseModel):
    file: str
    name: str
    line_start: int
    line_end: int
    methods: list[str] = Field(default_factory=list)
    bases: list[str] = Field(
        default_factory=list,
        description="Base class / superclass names",
    )
    decorators: list[str] = Field(
        default_factory=list,
        description="Decorator names applied to this class",
    )


class ImportInfo(BaseModel):
    file: str
    module: str
    names: list[str] = Field(default_factory=list)


class ASTData(BaseModel):
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[ImportInfo] = Field(default_factory=list)
    call_edges: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pairs of (caller_function, callee_function)",
    )


# Fields that add escaped-quote noise to LLM prompts and aren't needed
# for benchmark generation or similar code-generation tasks.
_VERBOSE_FUNCTION_FIELDS = {"docstring", "decorators", "is_async", "is_generator"}
_VERBOSE_CLASS_FIELDS = {"decorators"}


def slim_ast_for_prompt(ast_map: dict) -> dict:
    """Return a copy of ast_map with verbose / quote-heavy fields stripped.

    Prevents JSON-escaped quotes in docstrings and decorator strings from
    contaminating LLM-generated code (e.g. benchmark scripts).
    """

    def _slim_func(f: dict) -> dict:
        return {k: v for k, v in f.items() if k not in _VERBOSE_FUNCTION_FIELDS}

    def _slim_class(c: dict) -> dict:
        return {k: v for k, v in c.items() if k not in _VERBOSE_CLASS_FIELDS}

    return {
        **ast_map,
        "functions": [_slim_func(f) for f in ast_map.get("functions", [])],
        "classes": [_slim_class(c) for c in ast_map.get("classes", [])],
    }


class Hotspot(BaseModel):
    function_name: str
    file: str
    severity: str = Field(description="low, medium, high, critical")
    category: str = Field(
        description="e.g. N+1 query, blocking I/O, O(n^2) loop, inefficient algorithm"
    )
    reasoning: str


class AnalysisResult(BaseModel):
    language: str = Field(description="python or javascript/typescript")
    hotspots: list[Hotspot]
    summary: str


class TriageChunk(BaseModel):
    chunk_id: str = Field(description="e.g. 'chunk_1', 'data_layer'")
    label: str = Field(description="Human-readable chunk name, e.g. 'Database Layer'")
    files: list[str] = Field(description="List of relative file paths in this chunk")
    priority: int = Field(description="1 = highest priority, higher = lower priority")
    reasoning: str = Field(
        description="Why these files are grouped and why this priority"
    )


class TriageResult(BaseModel):
    language: str = Field(description="python or javascript/typescript")
    chunks: list[TriageChunk]
    total_files_scanned: int
    summary: str = Field(
        description="High-level overview of codebase structure and likely bottleneck areas"
    )


class BenchmarkScript(BaseModel):
    target_function: str
    file: str
    language: str
    script_content: str
    description: str


class BenchmarkBatch(BaseModel):
    scripts: list[BenchmarkScript]


class BenchmarkResult(BaseModel):
    function_name: str
    file: str
    avg_time_ms: float
    memory_peak_mb: float
    iterations: int
    raw_output: str = ""
    validation_fingerprint: str | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    file: str
    node_type: str = Field(
        default="function",
        description='One of: "api", "llm", "db", "condition", "function"',
    )
    inputs: dict[str, str] | None = Field(
        default=None,
        description="Key-value pairs describing the node's input parameters",
    )
    outputs: dict[str, str] | None = Field(
        default=None,
        description="Key-value pairs describing the node's return values",
    )
    metadata: dict[str, str] | None = Field(
        default=None,
        description="Extra context (e.g. HTTP method, DB table, model name)",
    )
    avg_time_ms: float | None = None
    memory_mb: float | None = None
    severity: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str = ""
    edge_type: str = Field(
        default="call",
        description='One of: "call", "branch_true", "branch_false", "loop_back"',
    )


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class OptimizationChange(BaseModel):
    file: str
    function_name: str
    original_snippet: str
    optimized_snippet: str
    explanation: str
    expected_improvement: str


class OptimizationPlan(BaseModel):
    changes: list[OptimizationChange]
    summary: str


class RadarAxis(BaseModel):
    axis: str
    before: float
    after: float


class CodeMarkScore(BaseModel):
    overall_before: float
    overall_after: float
    time_score: float
    time_score_before: float
    memory_score: float
    memory_score_before: float
    api_score: float
    api_score_before: float
    radar_data: list[RadarAxis]


class FunctionComparison(BaseModel):
    function_name: str
    file: str
    old_time_ms: float
    new_time_ms: float
    speedup_factor: float
    old_memory_mb: float
    new_memory_mb: float
    memory_reduction_pct: float


class ComparisonReport(BaseModel):
    functions: list[FunctionComparison]
    benchy_score: CodeMarkScore
    summary: str
    sandbox_specs: str = ""


class BenchmarkDetail(BaseModel):
    """A single benchmark with its script, before/after results, and summary."""

    function_name: str
    file: str
    language: str
    script_content: str
    before_time_ms: float
    before_memory_mb: float
    after_time_ms: float
    after_memory_mb: float
    speedup_factor: float
    summary: str = ""
