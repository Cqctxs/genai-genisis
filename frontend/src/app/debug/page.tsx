"use client";

import { useState } from "react";
import { LiveTelemetry } from "@/components/live-telemetry";
import { PerformanceGraph } from "@/components/performance-graph";
import { ScoreDashboard } from "@/components/score-dashboard";
import { PullRequestView } from "@/components/comparison-view";
import { ErrorBoundary } from "@/components/error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ComparisonReport, GraphData } from "@/lib/api";

const FAKE_MESSAGES = [
  { node: "clone", message: "Cloning repository https://github.com/acme/data-pipeline...", timestamp: Date.now() - 32000 },
  { node: "clone", message: "Repository cloned successfully (2.3 MB)", timestamp: Date.now() - 30000 },
  { node: "parse_ast", message: "Parsing AST for 14 Python files...", timestamp: Date.now() - 28000 },
  { node: "parse_ast", message: "Found 47 functions, 12 classes across 14 modules", timestamp: Date.now() - 26000 },
  { node: "analyze", message: "Analyzing call graph and dependency chains...", timestamp: Date.now() - 24000 },
  { node: "analyze", message: "Identified 6 hot paths with potential bottlenecks", timestamp: Date.now() - 22000 },
  { node: "generate_benchmarks", message: "Generating benchmark harness for 8 target functions...", timestamp: Date.now() - 20000 },
  { node: "run_benchmarks", message: "Spinning up E2B sandbox (2 vCPU, 4GB RAM)...", timestamp: Date.now() - 18000 },
  { node: "run_benchmarks", message: "Running baseline: process_batch [142.3ms avg over 100 iterations]", timestamp: Date.now() - 16000 },
  { node: "run_benchmarks", message: "Running baseline: transform_records [87.6ms avg]", timestamp: Date.now() - 14000 },
  { node: "run_benchmarks", message: "Running baseline: aggregate_metrics [234.1ms avg]", timestamp: Date.now() - 12000 },
  { node: "visualize", message: "Building performance graph with 47 nodes, 63 edges", timestamp: Date.now() - 10000 },
  { node: "optimize", message: "Optimizing process_batch: vectorized inner loop with numpy", timestamp: Date.now() - 8000 },
  { node: "optimize", message: "Optimizing aggregate_metrics: replaced O(n²) with hash-based merge", timestamp: Date.now() - 6000 },
  { node: "rerun_benchmarks", message: "Re-benchmarking optimized code...", timestamp: Date.now() - 4000 },
  { node: "rerun_benchmarks", message: "process_batch improved: 142.3ms → 31.2ms (4.6x)", timestamp: Date.now() - 3000 },
  { node: "report", message: "Computing CodeMark score delta...", timestamp: Date.now() - 2000 },
  { node: "cleanup", message: "Destroying sandbox. Analysis complete.", timestamp: Date.now() - 1000 },
];

const FAKE_GRAPH_DATA: GraphData = {
  nodes: [
    { id: "main", label: "main()", file: "app.py", avg_time_ms: 12.4, memory_mb: 1.2, severity: "low", position_x: 250, position_y: 0 },
    { id: "load_config", label: "load_config()", file: "config.py", avg_time_ms: 3.1, memory_mb: 0.5, severity: "low", position_x: 0, position_y: 120 },
    { id: "process_batch", label: "process_batch()", file: "pipeline.py", avg_time_ms: 142.3, memory_mb: 48.7, severity: "critical", position_x: 250, position_y: 120 },
    { id: "transform_records", label: "transform_records()", file: "transform.py", avg_time_ms: 87.6, memory_mb: 22.1, severity: "high", position_x: 500, position_y: 120 },
    { id: "validate_schema", label: "validate_schema()", file: "validation.py", avg_time_ms: 18.4, memory_mb: 3.2, severity: "medium", position_x: 0, position_y: 260 },
    { id: "aggregate_metrics", label: "aggregate_metrics()", file: "metrics.py", avg_time_ms: 234.1, memory_mb: 64.3, severity: "critical", position_x: 250, position_y: 260 },
    { id: "write_output", label: "write_output()", file: "io.py", avg_time_ms: 45.2, memory_mb: 8.1, severity: "medium", position_x: 500, position_y: 260 },
    { id: "format_report", label: "format_report()", file: "report.py", avg_time_ms: 5.8, memory_mb: 1.8, severity: "low", position_x: 250, position_y: 400 },
  ],
  edges: [
    { source: "main", target: "load_config", label: "init" },
    { source: "main", target: "process_batch", label: "calls" },
    { source: "main", target: "transform_records", label: "calls" },
    { source: "process_batch", target: "validate_schema", label: "validates" },
    { source: "process_batch", target: "aggregate_metrics", label: "aggregates" },
    { source: "transform_records", target: "write_output", label: "writes" },
    { source: "aggregate_metrics", target: "format_report", label: "formats" },
    { source: "write_output", target: "format_report", label: "appends" },
  ],
};

const FAKE_COMPARISON: ComparisonReport = {
  functions: [
    { function_name: "process_batch", file: "pipeline.py", old_time_ms: 142.3, new_time_ms: 31.2, speedup_factor: 4.6, old_memory_mb: 48.7, new_memory_mb: 22.1, memory_reduction_pct: 54.6 },
    { function_name: "aggregate_metrics", file: "metrics.py", old_time_ms: 234.1, new_time_ms: 41.8, speedup_factor: 5.6, old_memory_mb: 64.3, new_memory_mb: 18.4, memory_reduction_pct: 71.4 },
    { function_name: "transform_records", file: "transform.py", old_time_ms: 87.6, new_time_ms: 28.4, speedup_factor: 3.1, old_memory_mb: 22.1, new_memory_mb: 14.6, memory_reduction_pct: 33.9 },
    { function_name: "write_output", file: "io.py", old_time_ms: 45.2, new_time_ms: 18.9, speedup_factor: 2.4, old_memory_mb: 8.1, new_memory_mb: 5.2, memory_reduction_pct: 35.8 },
    { function_name: "validate_schema", file: "validation.py", old_time_ms: 18.4, new_time_ms: 7.1, speedup_factor: 2.6, old_memory_mb: 3.2, new_memory_mb: 2.0, memory_reduction_pct: 37.5 },
  ],
  codemark_score: {
    overall_before: 3420,
    overall_after: 8940,
    time_score: 91,
    memory_score: 85,
    complexity_score: 78,
    radar_data: [
      { axis: "Execution Time", before: 35, after: 91 },
      { axis: "Memory Usage", before: 28, after: 85 },
      { axis: "Complexity", before: 42, after: 78 },
      { axis: "Throughput", before: 31, after: 88 },
      { axis: "Cache Efficiency", before: 50, after: 82 },
    ],
  },
  summary:
    "Analysis of acme/data-pipeline identified 5 performance bottlenecks across the data processing pipeline. Key optimizations include vectorizing the inner loop in process_batch() using NumPy, replacing the O(n²) nested merge in aggregate_metrics() with a hash-based approach, and introducing chunked I/O writes. Overall CodeMark score improved from 3,420 to 8,940 — a 2.6x improvement across execution time, memory, and complexity dimensions.",
  sandbox_specs: "E2B Cloud Sandbox · 2 vCPU · 4 GB RAM · Python 3.12 · Ubuntu 22.04",
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

type Phase = "idle" | "analyzing" | "benchmarking" | "optimizing" | "re-benchmarking" | "scoring" | "complete" | "error";

const PHASES: Phase[] = ["idle", "analyzing", "benchmarking", "optimizing", "re-benchmarking", "scoring", "complete", "error"];

export default function DebugPage() {
  const [telemetryPhase, setTelemetryPhase] = useState<Phase>("complete");

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-neutral-800 px-6 py-3 flex items-center justify-between sticky top-0 bg-neutral-950/90 backdrop-blur-sm z-50">
        <h1 className="text-lg font-semibold tracking-tight">
          Code<span className="text-blue-500">Mark</span>
          <span className="text-xs ml-2 text-neutral-500 font-normal">Debug Mode</span>
        </h1>
        <a href="/" className="text-sm text-neutral-500 hover:text-white transition-colors">
          ← Back to app
        </a>
      </header>

      <main className="flex-1 p-6 max-w-7xl mx-auto w-full space-y-12">
        {/* ── Fonts ── */}
        <Section title="Fonts">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <FontSample label="font-sans (Inter)" className="font-sans" />
            <FontSample label="font-serif (Junicode Bold Italic)" className="font-serif" />
            <FontSample label="font-mono (Geist Mono)" className="font-mono" />
          </div>
        </Section>

        {/* ── Typography ── */}
        <Section title="Typography">
          <div className="space-y-4">
            <h1 className="text-5xl font-bold tracking-tight">Heading 1 — The quick brown fox</h1>
            <h2 className="text-3xl font-semibold tracking-tight">Heading 2 — Jumped over the lazy dog</h2>
            <h3 className="text-2xl font-medium">Heading 3 — Pack my box with five dozen liquor jugs</h3>
            <h4 className="text-xl">Heading 4 — How vexingly quick daft zebras jump</h4>
            <p className="text-base text-neutral-300">
              Body text — CodeMark analyzes your codebase using AST parsing, profiles bottlenecks in a sandboxed environment, and
              produces optimized code with a before/after performance score. Built with LangGraph, Gemini, and E2B.
            </p>
            <p className="text-sm text-neutral-500">
              Small text — Benchmarked on E2B Cloud Sandbox · 2 vCPU · 4 GB RAM · Python 3.12
            </p>
            <p className="font-serif text-3xl text-blue-400">
              Serif heading — Performance at a glance
            </p>
          </div>
        </Section>

        {/* ── Colors ── */}
        <Section title="Theme Colors">
          <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
            {[
              ["bg-background", "Background"],
              ["bg-foreground", "Foreground"],
              ["bg-card", "Card"],
              ["bg-primary", "Primary"],
              ["bg-secondary", "Secondary"],
              ["bg-muted", "Muted"],
              ["bg-accent", "Accent"],
              ["bg-destructive", "Destructive"],
              ["bg-border", "Border"],
              ["bg-ring", "Ring"],
              ["bg-blue-500", "Blue 500"],
              ["bg-green-400", "Green 400"],
            ].map(([cls, label]) => (
              <div key={cls} className="space-y-1.5">
                <div className={`h-12 rounded-lg border border-neutral-700 ${cls}`} />
                <p className="text-[10px] text-neutral-500 text-center">{label}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* ── Buttons ── */}
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
              <Button className="bg-blue-600 text-white hover:bg-blue-700">Custom Blue</Button>
              <Button className="bg-white text-black hover:bg-neutral-200">GitHub Style</Button>
            </div>
          </div>
        </Section>

        {/* ── Badges ── */}
        <Section title="Badges">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="default">Default</Badge>
            <Badge variant="secondary">Secondary</Badge>
            <Badge variant="outline">Outline</Badge>
            <Badge variant="destructive">Destructive</Badge>
            <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30">Custom Blue</Badge>
            <Badge className="bg-green-500/20 text-green-400 border-green-500/30">Success</Badge>
            <Badge className="bg-yellow-500/20 text-yellow-400 border-yellow-500/30">Warning</Badge>
          </div>
        </Section>

        {/* ── Inputs ── */}
        <Section title="Inputs">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-3xl">
            <Input placeholder="Default input" />
            <Input placeholder="Disabled input" disabled />
            <Input placeholder="With value" defaultValue="https://github.com/acme/repo" />
          </div>
        </Section>

        {/* ── Cards ── */}
        <Section title="Cards">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="bg-neutral-900 border-neutral-800">
              <CardHeader>
                <CardTitle className="text-sm">Default Card</CardTitle>
                <CardDescription>A simple card with header and content.</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-neutral-400">Card body content goes here. This demonstrates the standard card layout.</p>
              </CardContent>
            </Card>
            <Card className="bg-neutral-900 border-neutral-800">
              <CardContent className="pt-4 pb-4 space-y-2">
                <p className="text-xs text-neutral-500 uppercase tracking-wide">Execution Time</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-neutral-500 line-through text-sm">509.2ms</span>
                  <span className="text-xl font-semibold text-white">127.4ms</span>
                </div>
                <p className="text-xs font-medium text-green-400">+75% faster</p>
              </CardContent>
            </Card>
            <Card className="bg-neutral-900 border-neutral-800">
              <CardHeader>
                <CardTitle className="text-sm">With Footer</CardTitle>
              </CardHeader>
              <CardContent>
                <Skeleton className="h-20 w-full rounded-lg" />
              </CardContent>
              <CardFooter>
                <Button size="sm" variant="ghost" className="ml-auto">View details</Button>
              </CardFooter>
            </Card>
          </div>
        </Section>

        {/* ── Tabs ── */}
        <Section title="Tabs">
          <Tabs defaultValue="tab1">
            <TabsList className="bg-neutral-900 border border-neutral-800">
              <TabsTrigger value="tab1">Overview</TabsTrigger>
              <TabsTrigger value="tab2">Analytics</TabsTrigger>
              <TabsTrigger value="tab3">Settings</TabsTrigger>
              <TabsTrigger value="disabled" disabled>Disabled</TabsTrigger>
            </TabsList>
            <TabsContent value="tab1" className="mt-4">
              <Card className="bg-neutral-900 border-neutral-800">
                <CardContent className="py-6">
                  <p className="text-sm text-neutral-400">Tab 1 content — Overview panel with summary information.</p>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="tab2" className="mt-4">
              <Card className="bg-neutral-900 border-neutral-800">
                <CardContent className="py-6">
                  <p className="text-sm text-neutral-400">Tab 2 content — Analytics panel with charts and data.</p>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="tab3" className="mt-4">
              <Card className="bg-neutral-900 border-neutral-800">
                <CardContent className="py-6">
                  <p className="text-sm text-neutral-400">Tab 3 content — Settings and configuration options.</p>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </Section>

        {/* ── Skeleton ── */}
        <Section title="Skeleton Loading">
          <div className="space-y-3 max-w-md">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-32 w-full rounded-lg" />
          </div>
        </Section>

        <div className="border-t border-neutral-800 pt-12">
          <h2 className="text-2xl font-semibold tracking-tight mb-8">Feature Components</h2>
        </div>

        {/* ── Live Telemetry ── */}
        <Section title="Live Telemetry">
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
          <ErrorBoundary>
            <LiveTelemetry phase={telemetryPhase} messages={FAKE_MESSAGES} />
          </ErrorBoundary>
        </Section>

        {/* ── Performance Graph ── */}
        <Section title="Performance Graph">
          <ErrorBoundary>
            <PerformanceGraph graphData={FAKE_GRAPH_DATA} />
          </ErrorBoundary>
        </Section>

        {/* ── Score Dashboard ── */}
        <Section title="Score Dashboard">
          <ErrorBoundary>
            <ScoreDashboard comparison={FAKE_COMPARISON} />
          </ErrorBoundary>
        </Section>

        {/* ── Pull Request View ── */}
        <Section title="Pull Request View">
          <ErrorBoundary>
            <PullRequestView
              prUrl="https://github.com/acme/data-pipeline/pull/42"
              optimizedFiles={FAKE_OPTIMIZED_FILES}
              comparison={FAKE_COMPARISON}
            />
          </ErrorBoundary>
        </Section>

        {/* ── Error Boundary Demo ── */}
        <Section title="Error Boundary">
          <ErrorBoundary>
            <Card className="bg-neutral-900 border-red-900/50">
              <CardContent className="py-8 text-center space-y-3">
                <p className="text-sm text-red-400">Something went wrong</p>
                <p className="text-xs text-neutral-500 font-mono">
                  TypeError: Cannot read properties of undefined (reading &apos;map&apos;)
                </p>
                <Button variant="ghost" size="sm">
                  Try again
                </Button>
              </CardContent>
            </Card>
          </ErrorBoundary>
        </Section>
      </main>

      <footer className="border-t border-neutral-800 py-4 text-center text-xs text-neutral-600">
        CodeMark Debug Mode — All components rendered with synthetic data
      </footer>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-medium text-neutral-500 uppercase tracking-widest">{title}</h3>
        <div className="flex-1 h-px bg-neutral-800" />
      </div>
      {children}
    </section>
  );
}

function FontSample({ label, className }: { label: string; className: string }) {
  return (
    <Card className="bg-neutral-900 border-neutral-800">
      <CardContent className="pt-4 space-y-3">
        <p className="text-[10px] text-neutral-500 uppercase tracking-widest">{label}</p>
        <p className={`${className} text-3xl`}>Aa Bb Cc 123</p>
        <p className={`${className} text-lg text-neutral-300`}>The quick brown fox jumps over the lazy dog</p>
        <p className={`${className} text-sm text-neutral-500`}>
          ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789
        </p>
      </CardContent>
    </Card>
  );
}
