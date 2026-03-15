"use client";

import { useState } from "react";
import { ProgressStepper } from "@/components/progress-stepper";
import { PerformanceGraph } from "@/components/performance-graph";
import { ScoreDashboard } from "@/components/score-dashboard";
import { PullRequestView } from "@/components/comparison-view";
import { ErrorBoundary } from "@/components/error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ComparisonReport, GraphData } from "@/lib/api";

const FAKE_MESSAGES = [
  {
    node: "clone",
    message: "Cloning repository https://github.com/acme/data-pipeline...",
    timestamp: Date.now() - 32000,
  },
  {
    node: "clone",
    message: "Repository cloned successfully (2.3 MB)",
    timestamp: Date.now() - 30000,
  },
  {
    node: "parse_ast",
    message: "Parsing AST for 14 Python files...",
    timestamp: Date.now() - 28000,
  },
  {
    node: "parse_ast",
    message: "Found 47 functions, 12 classes across 14 modules",
    timestamp: Date.now() - 26000,
  },
  {
    node: "analyze",
    message: "Analyzing call graph and dependency chains...",
    timestamp: Date.now() - 24000,
  },
  {
    node: "analyze",
    message: "Identified 6 hot paths with potential bottlenecks",
    timestamp: Date.now() - 22000,
  },
  {
    node: "generate_benchmarks",
    message: "Generating benchmark harness for 8 target functions...",
    timestamp: Date.now() - 20000,
  },
  {
    node: "run_benchmarks",
    message: "Spinning up E2B sandbox (2 vCPU, 4GB RAM)...",
    timestamp: Date.now() - 18000,
  },
  {
    node: "run_benchmarks",
    message:
      "Running baseline: process_batch [142.3ms avg over 100 iterations]",
    timestamp: Date.now() - 16000,
  },
  {
    node: "run_benchmarks",
    message: "Running baseline: transform_records [87.6ms avg]",
    timestamp: Date.now() - 14000,
  },
  {
    node: "run_benchmarks",
    message: "Running baseline: aggregate_metrics [234.1ms avg]",
    timestamp: Date.now() - 12000,
  },
  {
    node: "visualize",
    message: "Building performance graph with 47 nodes, 63 edges",
    timestamp: Date.now() - 10000,
  },
  {
    node: "optimize",
    message: "Optimizing process_batch: vectorized inner loop with numpy",
    timestamp: Date.now() - 8000,
  },
  {
    node: "optimize",
    message:
      "Optimizing aggregate_metrics: replaced O(n²) with hash-based merge",
    timestamp: Date.now() - 6000,
  },
  {
    node: "rerun_benchmarks",
    message: "Re-benchmarking optimized code...",
    timestamp: Date.now() - 4000,
  },
  {
    node: "rerun_benchmarks",
    message: "process_batch improved: 142.3ms → 31.2ms (4.6x)",
    timestamp: Date.now() - 3000,
  },
  {
    node: "report",
    message: "Computing Benchy score delta...",
    timestamp: Date.now() - 2000,
  },
  {
    node: "cleanup",
    message: "Destroying sandbox. Analysis complete.",
    timestamp: Date.now() - 1000,
  },
];

const FAKE_GRAPH_DATA: GraphData = {
  nodes: [
    {
      id: "main",
      label: "Main Entrypoint",
      file: "app.py",
      node_type: "function",
      inputs: { records_path: "str", config_path: "str" },
      outputs: { report: "FormattedReport" },
      avg_time_ms: 12.4,
      memory_mb: 1.2,
      severity: "low",
    },
    {
      id: "load_config",
      label: "Load Configuration",
      file: "config.py",
      node_type: "function",
      inputs: { config_path: "str" },
      outputs: { config: "dict" },
      avg_time_ms: 3.1,
      memory_mb: 0.5,
      severity: "low",
    },
    {
      id: "fetch_remote",
      label: "Fetch Remote Data",
      file: "pipeline.py",
      node_type: "api",
      metadata: { method: "GET", endpoint: "/api/v2/records" },
      inputs: { api_key: "str", page: "int" },
      outputs: { records: "list[dict]" },
      avg_time_ms: 320.5,
      memory_mb: 12.4,
      severity: "high",
    },
    {
      id: "cache_check",
      label: "Cache Hit?",
      file: "pipeline.py",
      node_type: "condition",
      metadata: { condition: "record_hash in cache" },
      avg_time_ms: 0.8,
      memory_mb: 0.1,
      severity: "low",
    },
    {
      id: "query_orders",
      label: "Query Orders Table",
      file: "db.py",
      node_type: "db",
      metadata: { table: "orders", operation: "SELECT" },
      inputs: { user_id: "int", date_range: "tuple" },
      outputs: { rows: "list[OrderRow]" },
      avg_time_ms: 234.1,
      memory_mb: 64.3,
      severity: "critical",
    },
    {
      id: "process_batch",
      label: "Process Batch",
      file: "pipeline.py",
      node_type: "function",
      inputs: { records: "list[dict]", batch_size: "int" },
      outputs: { processed: "list[dict]" },
      avg_time_ms: 142.3,
      memory_mb: 48.7,
      severity: "critical",
    },
    {
      id: "analyze_sentiment",
      label: "Analyze Sentiment",
      file: "ai.py",
      node_type: "llm",
      metadata: {
        model: "gemini-3-flash",
        purpose: "Classify record sentiment",
      },
      inputs: { text: "str" },
      outputs: { sentiment: "str", confidence: "float" },
      avg_time_ms: 890.2,
      memory_mb: 2.1,
      severity: "high",
    },
    {
      id: "aggregate_metrics",
      label: "Aggregate Metrics",
      file: "metrics.py",
      node_type: "function",
      inputs: { processed: "list[dict]" },
      outputs: { summary: "dict" },
      avg_time_ms: 87.6,
      memory_mb: 22.1,
      severity: "medium",
    },
    {
      id: "format_report",
      label: "Format Report",
      file: "report.py",
      node_type: "function",
      inputs: { summary: "dict", orders: "list" },
      outputs: { report: "FormattedReport" },
      avg_time_ms: 5.8,
      memory_mb: 1.8,
      severity: "low",
    },
  ],
  edges: [
    { source: "main", target: "load_config", label: "init", edge_type: "call" },
    { source: "main", target: "fetch_remote", label: "", edge_type: "call" },
    {
      source: "fetch_remote",
      target: "cache_check",
      label: "",
      edge_type: "call",
    },
    {
      source: "cache_check",
      target: "process_batch",
      label: "cache hit",
      edge_type: "branch_true",
    },
    {
      source: "cache_check",
      target: "query_orders",
      label: "cache miss",
      edge_type: "branch_false",
    },
    {
      source: "query_orders",
      target: "aggregate_metrics",
      label: "",
      edge_type: "call",
    },
    {
      source: "process_batch",
      target: "analyze_sentiment",
      label: "",
      edge_type: "call",
    },
    {
      source: "analyze_sentiment",
      target: "process_batch",
      label: "for each record",
      edge_type: "loop_back",
    },
    {
      source: "process_batch",
      target: "aggregate_metrics",
      label: "",
      edge_type: "call",
    },
    {
      source: "aggregate_metrics",
      target: "format_report",
      label: "",
      edge_type: "call",
    },
  ],
};

const FAKE_COMPARISON: ComparisonReport = {
  functions: [
    {
      function_name: "process_batch",
      file: "pipeline.py",
      old_time_ms: 142.3,
      new_time_ms: 31.2,
      speedup_factor: 4.6,
      old_memory_mb: 48.7,
      new_memory_mb: 22.1,
      memory_reduction_pct: 54.6,
    },
    {
      function_name: "aggregate_metrics",
      file: "metrics.py",
      old_time_ms: 234.1,
      new_time_ms: 41.8,
      speedup_factor: 5.6,
      old_memory_mb: 64.3,
      new_memory_mb: 18.4,
      memory_reduction_pct: 71.4,
    },
    {
      function_name: "transform_records",
      file: "transform.py",
      old_time_ms: 87.6,
      new_time_ms: 28.4,
      speedup_factor: 3.1,
      old_memory_mb: 22.1,
      new_memory_mb: 14.6,
      memory_reduction_pct: 33.9,
    },
    {
      function_name: "write_output",
      file: "io.py",
      old_time_ms: 45.2,
      new_time_ms: 18.9,
      speedup_factor: 2.4,
      old_memory_mb: 8.1,
      new_memory_mb: 5.2,
      memory_reduction_pct: 35.8,
    },
    {
      function_name: "validate_schema",
      file: "validation.py",
      old_time_ms: 18.4,
      new_time_ms: 7.1,
      speedup_factor: 2.6,
      old_memory_mb: 3.2,
      new_memory_mb: 2.0,
      memory_reduction_pct: 37.5,
    },
  ],
  benchy_score: {
    overall_before: 3420,
    overall_after: 8940,
    time_score: 91,
    time_score_before: 35,
    memory_score: 85,
    memory_score_before: 28,
    api_score: 78,
    api_score_before: 42,
    radar_data: [
      { axis: "Execution Time", before: 35, after: 91 },
      { axis: "Memory Usage", before: 28, after: 85 },
      { axis: "Complexity", before: 42, after: 78 },
      { axis: "Throughput", before: 31, after: 88 },
      { axis: "Cache Efficiency", before: 50, after: 82 },
    ],
  },
  summary:
    "Analysis of acme/data-pipeline identified 5 performance bottlenecks across the data processing pipeline. Key optimizations include vectorizing the inner loop in process_batch() using NumPy, replacing the O(n²) nested merge in aggregate_metrics() with a hash-based approach, and introducing chunked I/O writes. Overall Benchy score improved from 3,420 to 8,940 — a 2.6x improvement across execution time, memory, and complexity dimensions.",
  sandbox_specs:
    "E2B Cloud Sandbox · 2 vCPU · 4 GB RAM · Python 3.12 · Ubuntu 22.04",
};

const FAKE_OPTIMIZED_FILES: Record<string, string> = {
  "pipeline.py": `import numpy as np
from typing import List, Dict, Any

def process_batch(records: List[Dict[str, Any]], batch_size: int = 1000) -> List[Dict[str, Any]]:
    """Process records in vectorized batches using NumPy."""
    results = []
    arr = np.array([r["value"] for r in records], dtype=np.float64)

    for i in range(0, len(arr), batch_size):
        chunk = arr[i : i + batch_size]
        normalized = (chunk - chunk.mean()) / (chunk.std() + 1e-8)
        scaled = normalized * 100
        results.extend(
            {**records[i + j], "processed_value": float(scaled[j])}
            for j in range(len(chunk))
        )

    return results
`,
  "metrics.py": `from collections import defaultdict
from typing import List, Dict, Any

def aggregate_metrics(records: List[Dict[str, Any]]) -> Dict[str, float]:
    """Aggregate metrics using hash-based merge (O(n))."""
    buckets: Dict[str, List[float]] = defaultdict(list)

    for record in records:
        key = record["category"]
        buckets[key].append(record["processed_value"])

    return {
        key: sum(values) / len(values)
        for key, values in buckets.items()
    }
`,
  "transform.py": `from typing import List, Dict, Any

def transform_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform records with pre-compiled field mapping."""
    field_map = {"ts": "timestamp", "val": "value", "cat": "category"}

    return [
        {field_map.get(k, k): v for k, v in record.items()}
        for record in records
    ]
`,
};

type Phase =
  | "idle"
  | "analyzing"
  | "benchmarking"
  | "optimizing"
  | "re-benchmarking"
  | "scoring"
  | "complete"
  | "error";

const PHASES: Phase[] = [
  "idle",
  "analyzing",
  "benchmarking",
  "optimizing",
  "re-benchmarking",
  "scoring",
  "complete",
  "error",
];

export default function DebugPage() {
  const [telemetryPhase, setTelemetryPhase] = useState<Phase>("complete");

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden">
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <div className="flex items-center gap-3">
            <a
              href="/"
              className="font-serif text-xl hover:text-light/80 transition-colors"
            >
              Benchy
            </a>
            <span className="text-xs font-mono text-light/40">debug mode</span>
          </div>
          <a
            href="/"
            className="text-xs font-mono text-light/60 hover:text-light transition-colors"
          >
            ← back to app
          </a>
        </nav>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 sm:px-10 py-8">
          <div className="max-w-7xl mx-auto w-full space-y-12">
            {/* Fonts */}
            <Section title="Fonts">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <FontSample label="font-sans (Inter)" className="font-sans" />
                <FontSample
                  label="font-serif (Junicode Bold Italic)"
                  className="font-serif"
                />
                <FontSample
                  label="font-mono (Fira Code)"
                  className="font-mono"
                />
              </div>
            </Section>

            {/* Typography */}
            <Section title="Typography">
              <div className="space-y-4">
                <h1 className="text-5xl font-bold tracking-tight">
                  Heading 1 — The quick brown fox
                </h1>
                <h2 className="text-3xl font-semibold tracking-tight">
                  Heading 2 — Jumped over the lazy dog
                </h2>
                <h3 className="text-2xl font-medium">
                  Heading 3 — Pack my box with five dozen liquor jugs
                </h3>
                <h4 className="text-xl">
                  Heading 4 — How vexingly quick daft zebras jump
                </h4>
                <p className="text-base text-light/70">
                  Body text — Benchy analyzes your codebase using AST parsing,
                  profiles bottlenecks in a sandboxed environment, and produces
                  optimized code with a before/after performance score. Built
                  with LangGraph, Gemini, and E2B.
                </p>
                <p className="text-sm text-light/40">
                  Small text — Benchmarked on E2B Cloud Sandbox · 2 vCPU · 4 GB
                  RAM · Python 3.12
                </p>
                <p className="font-serif text-3xl text-accent-blue">
                  Serif heading — Performance at a glance
                </p>
              </div>
            </Section>

            {/* Colors */}
            <Section title="Theme Colors">
              <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
                {[
                  ["bg-light", "Light"],
                  ["bg-dark", "Dark"],
                  ["bg-accent-red", "Accent Red"],
                  ["bg-accent-orange", "Accent Orange"],
                  ["bg-accent-green", "Accent Green"],
                  ["bg-accent-blue", "Accent Blue"],
                  ["bg-accent-purple", "Accent Purple"],
                  ["bg-primary", "Primary"],
                  ["bg-secondary", "Secondary"],
                  ["bg-muted", "Muted"],
                  ["bg-destructive", "Destructive"],
                  ["bg-border", "Border"],
                ].map(([cls, label]) => (
                  <div key={cls} className="space-y-1.5">
                    <div
                      className={`h-12 rounded-lg ring-1 ring-light/15 ${cls}`}
                    />
                    <p className="text-[10px] text-light/40 text-center">
                      {label}
                    </p>
                  </div>
                ))}
              </div>
            </Section>

            {/* Buttons */}
            <Section title="Buttons">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="default">Default</Button>
                  <Button variant="secondary">Secondary</Button>
                  <Button variant="outline">Outline</Button>
                  <Button variant="ghost">Ghost</Button>
                  <Button variant="destructive">Destructive</Button>
                  <Button variant="link">Link</Button>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="xs">Extra Small</Button>
                  <Button size="sm">Small</Button>
                  <Button size="default">Default</Button>
                  <Button size="lg">Large</Button>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button disabled>Disabled</Button>
                  <Button className="bg-accent-blue text-light hover:bg-accent-blue/80">
                    Accent Blue
                  </Button>
                  <Button className="bg-accent-green text-dark hover:bg-accent-green/80">
                    Accent Green
                  </Button>
                  <Button className="bg-light text-dark hover:bg-light/80">
                    Light Style
                  </Button>
                </div>
              </div>
            </Section>

            {/* Badges */}
            <Section title="Badges">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="default">Default</Badge>
                <Badge variant="secondary">Secondary</Badge>
                <Badge variant="outline">Outline</Badge>
                <Badge variant="destructive">Destructive</Badge>
                <Badge className="bg-accent-red/20 text-accent-red border-accent-red/30">
                  Red
                </Badge>
                <Badge className="bg-accent-orange/20 text-accent-orange border-accent-orange/30">
                  Orange
                </Badge>
                <Badge className="bg-accent-green/20 text-accent-green border-accent-green/30">
                  Green
                </Badge>
                <Badge className="bg-accent-blue/20 text-accent-blue border-accent-blue/30">
                  Blue
                </Badge>
                <Badge className="bg-accent-purple/20 text-accent-purple border-accent-purple/30">
                  Purple
                </Badge>
              </div>
            </Section>

            {/* Inputs */}
            <Section title="Inputs">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-3xl">
                <Input placeholder="Default input" />
                <Input placeholder="Disabled input" disabled />
                <Input
                  placeholder="With value"
                  defaultValue="https://github.com/acme/repo"
                />
              </div>
            </Section>

            {/* Cards */}
            <Section title="Cards">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card className="bg-light/5">
                  <CardHeader>
                    <CardTitle className="text-sm">Default Card</CardTitle>
                    <CardDescription>
                      A simple card with header and content.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-light/50">
                      Card body content goes here. This demonstrates the
                      standard card layout.
                    </p>
                  </CardContent>
                </Card>
                <Card className="bg-light/5">
                  <CardContent className="pt-4 pb-4 space-y-2">
                    <p className="text-xs text-light/40 uppercase tracking-wide">
                      Execution Time
                    </p>
                    <div className="flex items-baseline gap-2">
                      <span className="text-light/40 line-through text-sm">
                        509.2ms
                      </span>
                      <span className="text-xl font-semibold text-light">
                        127.4ms
                      </span>
                    </div>
                    <p className="text-xs font-medium text-accent-green">
                      +75% faster
                    </p>
                  </CardContent>
                </Card>
                <Card className="bg-light/5">
                  <CardHeader>
                    <CardTitle className="text-sm">With Footer</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Skeleton className="h-20 w-full rounded-lg" />
                  </CardContent>
                  <CardFooter>
                    <Button size="sm" variant="ghost" className="ml-auto">
                      View details
                    </Button>
                  </CardFooter>
                </Card>
              </div>
            </Section>

            {/* Tabs */}
            <Section title="Tabs">
              <Tabs defaultValue="tab1">
                <TabsList className="bg-light/5 border border-light/10">
                  <TabsTrigger value="tab1">Overview</TabsTrigger>
                  <TabsTrigger value="tab2">Analytics</TabsTrigger>
                  <TabsTrigger value="tab3">Settings</TabsTrigger>
                  <TabsTrigger value="disabled" disabled>
                    Disabled
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="tab1" className="mt-4">
                  <Card className="bg-light/5">
                    <CardContent className="py-6">
                      <p className="text-sm text-light/50">
                        Tab 1 content — Overview panel with summary information.
                      </p>
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="tab2" className="mt-4">
                  <Card className="bg-light/5">
                    <CardContent className="py-6">
                      <p className="text-sm text-light/50">
                        Tab 2 content — Analytics panel with charts and data.
                      </p>
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="tab3" className="mt-4">
                  <Card className="bg-light/5">
                    <CardContent className="py-6">
                      <p className="text-sm text-light/50">
                        Tab 3 content — Settings and configuration options.
                      </p>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </Section>

            {/* Skeleton */}
            <Section title="Skeleton Loading">
              <div className="space-y-3 max-w-md">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
                <Skeleton className="h-32 w-full rounded-lg" />
              </div>
            </Section>

            <div className="border-t border-light/10 pt-12">
              <h2 className="text-2xl font-semibold tracking-tight mb-8">
                Feature Components
              </h2>
            </div>

            {/* Progress Stepper */}
            <Section title="Progress Stepper">
              <div className="flex flex-wrap gap-2 mb-4">
                {PHASES.map((p) => (
                  <Button
                    key={p}
                    size="xs"
                    variant={telemetryPhase === p ? "default" : "outline"}
                    onClick={() => setTelemetryPhase(p)}
                  >
                    {p}
                  </Button>
                ))}
              </div>
              {/* ErrorBoundary / LiveTelemetry removed */}
            </Section>

            {/* Performance Graph */}
            <Section title="Performance Graph">
              <ErrorBoundary>
                <PerformanceGraph graphData={FAKE_GRAPH_DATA} />
              </ErrorBoundary>
            </Section>

            {/* Score Dashboard */}
            <Section title="Score Dashboard">
              <ErrorBoundary>
                <ScoreDashboard comparison={FAKE_COMPARISON} />
              </ErrorBoundary>
            </Section>

            {/* Pull Request View */}
            <Section title="Pull Request View">
              <ErrorBoundary>
                <PullRequestView
                  prUrl="https://github.com/acme/data-pipeline/pull/42"
                  optimizedFiles={FAKE_OPTIMIZED_FILES}
                  comparison={FAKE_COMPARISON}
                />
              </ErrorBoundary>
            </Section>

            {/* Error Boundary Demo */}
            <Section title="Error Boundary">
              <ErrorBoundary>
                <Card className="bg-light/5 ring-accent-red/20">
                  <CardContent className="py-8 text-center space-y-3">
                    <p className="text-sm text-accent-red">
                      Something went wrong
                    </p>
                    <p className="text-xs text-light/40 font-mono">
                      TypeError: Cannot read properties of undefined (reading
                      &apos;map&apos;)
                    </p>
                    <Button variant="ghost" size="sm">
                      Try again
                    </Button>
                  </CardContent>
                </Card>
              </ErrorBoundary>
            </Section>
          </div>
        </div>

        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-accent-purple" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
          </div>
          <p className="font-mono text-[11px] text-light/30">
            ● debug mode · all components rendered with synthetic data
          </p>
          <span className="w-2 h-2 rounded-full bg-light/20" />
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-medium text-light/40 uppercase tracking-widest">
          {title}
        </h3>
        <div className="flex-1 h-px bg-light/10" />
      </div>
      {children}
    </section>
  );
}

function FontSample({
  label,
  className,
}: {
  label: string;
  className: string;
}) {
  return (
    <Card className="bg-light/5">
      <CardContent className="pt-4 space-y-3">
        <p className="text-[10px] text-light/40 uppercase tracking-widest">
          {label}
        </p>
        <p className={`${className} text-3xl`}>Aa Bb Cc 123</p>
        <p className={`${className} text-lg text-light/70`}>
          The quick brown fox jumps over the lazy dog
        </p>
        <p className={`${className} text-sm text-light/40`}>
          ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789
        </p>
      </CardContent>
    </Card>
  );
}
