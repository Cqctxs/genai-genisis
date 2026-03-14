const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface GitHubRepo {
  id: number;
  full_name: string;
  name: string;
  owner: string;
  owner_avatar: string;
  html_url: string;
  description: string;
  language: string;
  stargazers_count: number;
  private: boolean;
  fork: boolean;
  updated_at: string;
}

export async function listRepos(githubToken: string): Promise<GitHubRepo[]> {
  const res = await fetch(
    `${API_URL}/api/repos?github_token=${encodeURIComponent(githubToken)}`
  );

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Failed to fetch repositories");
  }

  return res.json();
}

export interface AnalyzeResponse {
  job_id: string;
}

export interface StreamEvent {
  event: string;
  data: string;
}

export interface GraphNode {
  id: string;
  label: string;
  file: string;
  avg_time_ms: number | null;
  memory_mb: number | null;
  severity: string | null;
  position_x: number;
  position_y: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface RadarAxis {
  axis: string;
  before: number;
  after: number;
}

export interface BenchyScore {
  overall_before: number;
  overall_after: number;
  time_score: number;
  memory_score: number;
  complexity_score: number;
  radar_data: RadarAxis[];
}

export interface FunctionComparison {
  function_name: string;
  file: string;
  old_time_ms: number;
  new_time_ms: number;
  speedup_factor: number;
  old_memory_mb: number;
  new_memory_mb: number;
  memory_reduction_pct: number;
}

export interface ComparisonReport {
  functions: FunctionComparison[];
  benchy_score: BenchyScore;
  summary: string;
  sandbox_specs: string;
}

export interface JobResult {
  graph_data: GraphData;
  comparison: ComparisonReport;
  optimized_files: Record<string, string>;
  initial_results: any[];
  final_results: any[];
  analysis: any;
  pr_url: string;
  pr_status?: string;
  pr_error?: string | null;
}

export async function startAnalysis(
  repoUrl: string,
  githubToken: string,
  optimizationBias: string = "balanced"
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_URL}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo_url: repoUrl,
      github_token: githubToken,
      optimization_bias: optimizationBias,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Failed to start analysis");
  }

  return res.json();
}

export function streamJob(
  jobId: string,
  onEvent: (event: { event: string; data: any }) => void,
  onError: (error: Error) => void,
  onComplete: () => void
): () => void {
  const eventSource = new EventSource(`${API_URL}/api/stream/${jobId}`);

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "message", data });
    } catch {
      onEvent({ event: "message", data: e.data });
    }
  };

  eventSource.addEventListener("progress", (e: any) => {
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "progress", data });
    } catch {
      onEvent({ event: "progress", data: e.data });
    }
  });

  eventSource.addEventListener("complete", (e: any) => {
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "complete", data });
    } catch {
      onEvent({ event: "complete", data: e.data });
    }
    eventSource.close();
    onComplete();
  });

  eventSource.addEventListener("error", (e: any) => {
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "error", data });
    } catch {
      // SSE connection error
    }
    eventSource.close();
    onError(new Error("Stream connection lost"));
  });

  eventSource.onerror = () => {
    eventSource.close();
    onError(new Error("Stream connection lost"));
  };

  return () => eventSource.close();
}

export async function getResults(jobId: string): Promise<JobResult> {
  const res = await fetch(`${API_URL}/api/results/${jobId}`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Failed to fetch results");
  }
  return res.json();
}
