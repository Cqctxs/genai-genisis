from pydantic import BaseModel, Field


class FunctionInfo(BaseModel):
    file: str
    name: str
    line_start: int
    line_end: int
    params: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)


class ClassInfo(BaseModel):
    file: str
    name: str
    line_start: int
    line_end: int
    methods: list[str] = Field(default_factory=list)


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
    reasoning: str = Field(description="Why these files are grouped and why this priority")


class TriageResult(BaseModel):
    language: str = Field(description="python or javascript/typescript")
    chunks: list[TriageChunk]
    total_files_scanned: int
    summary: str = Field(description="High-level overview of codebase structure and likely bottleneck areas")


class BenchmarkScript(BaseModel):
    target_function: str
    file: str
    language: str
    script_content: str
    description: str


class BenchmarkResult(BaseModel):
    function_name: str
    file: str
    avg_time_ms: float
    memory_peak_mb: float
    iterations: int
    raw_output: str = ""


class GraphNode(BaseModel):
    id: str
    label: str
    file: str
    avg_time_ms: float | None = None
    memory_mb: float | None = None
    severity: str | None = None
    position_x: float = 0
    position_y: float = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str = ""


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
    memory_score: float
    complexity_score: float
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
