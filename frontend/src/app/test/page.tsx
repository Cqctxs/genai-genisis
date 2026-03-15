"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { PerformanceGraph } from "@/components/performance-graph";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { listRepos, startAnalysis, fetchPreviewGraph, streamJob, type GitHubRepo, type GraphData } from "@/lib/api";
import { Search, ArrowRight, Zap, Scale, HardDrive, ScanSearch, FastForward } from "lucide-react";

const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: "#3178c6",
  JavaScript: "#f1e05a",
  Python: "#3572A5",
  Go: "#00ADD8",
  Rust: "#dea584",
  Java: "#b07219",
  "C++": "#f34b7d",
  C: "#555555",
  Ruby: "#701516",
  PHP: "#4F5D95",
  Swift: "#F05138",
  Kotlin: "#A97BFF",
  Dart: "#00B4AB",
  Shell: "#89e051",
  HTML: "#e34c26",
  CSS: "#563d7c",
};

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

type OptimizationBias = "speed" | "balanced" | "memory";
type AnalysisMode = "detailed" | "fast";
type RepoMode = "browse" | "url";

const BIAS_OPTIONS: {
  value: OptimizationBias;
  label: string;
  icon: React.ReactNode;
  description: string;
}[] = [
  {
    value: "speed",
    label: "Speed",
    icon: <Zap className="w-4 h-4" />,
    description: "Prioritize fast execution over deep memory analysis",
  },
  {
    value: "balanced",
    label: "Balanced",
    icon: <Scale className="w-4 h-4" />,
    description: "Balance speed and memory optimizations equally",
  },
  {
    value: "memory",
    label: "Memory",
    icon: <HardDrive className="w-4 h-4" />,
    description: "Minimize memory footprint at the cost of speed",
  },
];

const ANALYSIS_OPTIONS: {
  value: AnalysisMode;
  label: string;
  icon: React.ReactNode;
  description: string;
}[] = [
  {
    value: "detailed",
    label: "Detailed",
    icon: <ScanSearch className="w-4 h-4" />,
    description: "Uses an AI reviewer to double-check AI optimizations",
  },
  {
    value: "fast",
    label: "Fast (Skip Review)",
    icon: <FastForward className="w-4 h-4" />,
    description: "Skips the reviewer verification node for faster results",
  },
];

/* ------------------------------------------------------------------ */
/*  Pipeline node-to-phase mapping for animation                       */
/* ------------------------------------------------------------------ */

type Phase =
  | "idle"
  | "analyzing"
  | "benchmarking"
  | "optimizing"
  | "re-benchmarking"
  | "scoring"
  | "complete"
  | "error";





/* ------------------------------------------------------------------ */
/*  Main page component                                                */
/* ------------------------------------------------------------------ */

type ViewState = "repo-select" | "graph-config" | "analyzing";

export default function TestPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  // Panel state
  const [repoMode, setRepoMode] = useState<RepoMode>("browse");
  const [optimizationBias, setOptimizationBias] = useState<OptimizationBias>("balanced");
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("detailed");

  // Repo browsing
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [fetchState, setFetchState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [fetchError, setFetchError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepo | null>(null);

  // URL input
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");

  // Execution state
  const [phase, setPhase] = useState<Phase>("idle");
  const [currentView, setCurrentView] = useState<ViewState>("repo-select");
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [currentMessage, setCurrentMessage] = useState("");
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // panelCollapsed is true when analysis is running
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  // userHiddenPanel allows the user to manually hide the panel to view the graph
  const [userHiddenPanel, setUserHiddenPanel] = useState(false);

  // Auth redirect
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  // Fetch repos
  const accessToken = (session as any)?.accessToken ?? null;
  useEffect(() => {
    if (!accessToken || fetchState !== "idle") return;
    setFetchState("loading");
    listRepos(accessToken)
      .then((data) => {
        setRepos(data);
        setFetchState("loaded");
      })
      .catch((err) => {
        setFetchError(err.message);
        setFetchState("error");
      });
  }, [accessToken, fetchState]);

  const filtered = useMemo(() => {
    if (!search.trim()) return repos;
    const q = search.toLowerCase();
    return repos.filter(
      (r) =>
        r.full_name.toLowerCase().includes(q) ||
        r.description?.toLowerCase().includes(q) ||
        r.language?.toLowerCase().includes(q),
    );
  }, [repos, search]);

  // Build graph nodes/edges with phase-based styling

  const totalNodes = graphData?.nodes.length ?? 0;

  const handleNodeClick = useCallback((id: string) => {
    if (currentView !== "graph-config") return;
    setSelectedNodeIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  }, [currentView]);

  const handleGenerateFlowchart = useCallback(async (targetUrl: string) => {
    if (!accessToken) return;
    setPreviewLoading(true);
    setCurrentMessage("Starting graph generation...");
    setPhase("analyzing");

    try {
      const { job_id } = await fetchPreviewGraph(targetUrl, accessToken);

      streamJob(
        job_id,
        (event) => {
          if (event.event === "progress" && event.data) {
            const msg = typeof event.data === "string" ? event.data : event.data.message;
            if (msg) setCurrentMessage(msg);
          }
          if (event.event === "complete" && event.data) {
            const result = event.data;
            const gd = result.graph_data;
            if (gd) {
              setGraphData(gd);
              setSelectedNodeIds(gd.nodes.map((n: any) => n.id));
              setCurrentView("graph-config");
              setPanelCollapsed(false);
            }
            setPhase("idle");
            setPreviewLoading(false);
            setCurrentMessage("");
          }
        },
        (err) => {
          setPhase("error");
          setCurrentMessage(err.message);
          setPreviewLoading(false);
        },
        () => {
          // onComplete (stream closed) — state already set above
        },
      );
    } catch (err: any) {
      setPhase("error");
      setCurrentMessage(err.message || "Failed to generate graph");
      setPreviewLoading(false);
    }
  }, [accessToken]);

  const handleBrowseAnalyze = () => {
    if (!selectedRepo || previewLoading) return;
    handleGenerateFlowchart(selectedRepo.html_url);
  };

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (previewLoading) return;
    const trimmed = url.trim().replace(/\/+$/, "");
    if (!GITHUB_URL_REGEX.test(trimmed)) {
      setUrlError("Please enter a valid GitHub repository URL");
      return;
    }
    setUrlError("");
    handleGenerateFlowchart(trimmed);
  };

  // Analyze handler
  const handleStartOptimization = useCallback(
    async () => {
      if (!accessToken) return;
      
      const targetUrl = repoMode === "url" ? url.trim() : selectedRepo?.html_url;
      if (!targetUrl) return;

      setPhase("analyzing");
      setCurrentView("analyzing");
      setCurrentMessage("Starting analysis...");
      setPanelCollapsed(true);

      try {
        const { job_id } = await startAnalysis(
          targetUrl,
          accessToken,
          optimizationBias,
          analysisMode === "fast",
        );

        streamJob(
          job_id,
          (event) => {
            if (event.event === "progress" && event.data) {
              const { message } = event.data;
              setCurrentMessage(message);
              const msgLower = message.toLowerCase();
              if (msgLower.includes("cloning") || msgLower.includes("parsing") || msgLower.includes("triaging")) {
                setPhase("analyzing");
              } else if (msgLower.includes("re-run") || msgLower.includes("re-optimizing")) {
                setPhase("re-benchmarking");
              } else if (msgLower.includes("streaming analysis") && msgLower.includes("benchmarks per chunk")) {
                setPhase("benchmarking");
              } else if (msgLower.includes("generating visualization") || msgLower.includes("optimizations")) {
                setPhase("optimizing");
              } else if (msgLower.includes("report") || msgLower.includes("pull request")) {
                setPhase("scoring");
              }
            }
            if (event.event === "complete") {
              setPhase("complete");
              router.push("/job/" + job_id);
            }
          },
          (err) => {
            setPhase("error");
            setCurrentMessage(err.message);
          },
          () => {
            router.push("/job/" + job_id);
          },
        );
      } catch (err: any) {
        setPhase("error");
        setCurrentMessage(err.message || "Failed to start analysis");
      }
    },
    [accessToken, optimizationBias, analysisMode, router, repoMode, url, selectedRepo],
  );

  const handleReset = () => {
    setPhase("idle");
    setCurrentMessage("");
    setPanelCollapsed(false);
    setCurrentView("repo-select");
    setGraphData(null);
    setSelectedNodeIds([]);
    setPreviewLoading(false);
  };

  const isRunning = phase !== "idle" && phase !== "error" && phase !== "complete";

  const statusText =
    phase === "idle"
      ? "ready · configure and launch analysis"
      : phase === "error"
        ? "error encountered"
        : phase === "complete"
          ? "analysis complete"
          : `${phase}...`;

  if (status === "loading") {
    return (
      <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
        <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex items-center justify-center">
          <span className="animate-pulse text-light/40 font-mono text-sm">loading...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden relative">
        {/* Nav */}
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10 z-20 bg-dark/80 backdrop-blur-sm">
          <a
            href="/"
            className="flex items-center gap-2 hover:opacity-80 transition-opacity text-3xl"
          >
            <img src="/images/benchy_light.svg" alt="Benchy" className="h-8" />
            <span className="font-serif">Benchy</span>
          </a>
          <div className="flex items-center gap-6">
            <span className="text-xs font-mono text-light/40">{session?.user?.name}</span>
            <a
              href="/dashboard"
              className="text-xs font-mono text-light/40 hover:text-light/70 transition-colors"
            >
              /dashboard
            </a>
          </div>
        </nav>

        {/* Background flowchart layer */}
        <div className={`absolute inset-0 z-0 transition-opacity duration-700 pointer-events-auto ${
          currentView === 'repo-select' ? 'opacity-15 blur-sm' : 'opacity-100'
        }`} style={{ top: "57px" }}>
          {graphData ? (
            <PerformanceGraph
              graphData={graphData}
              variant="fullscreen"
              selectedNodeIds={selectedNodeIds}
              onNodeClick={handleNodeClick}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              {previewLoading && (
                <div className="text-center space-y-3">
                  <div className="w-8 h-8 border-2 border-accent-blue/30 border-t-accent-blue rounded-full animate-spin mx-auto" />
                  <p className="text-xs text-light/40 font-mono">{currentMessage}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Foreground content */}
        <div className={`flex-1 min-h-0 flex items-center z-10 px-6 py-8 pointer-events-none relative transition-all duration-700 ${
          currentView === "repo-select" ? "justify-center" : "justify-end"
        }`}>
          
          {/* User Expand/Collapse Toggle Button */}
          {currentView !== "repo-select" && !panelCollapsed && (
            <button
              onClick={() => setUserHiddenPanel((prev) => !prev)}
              className="absolute top-6 right-6 z-50 p-2.5 rounded-xl border border-light/10 bg-dark/90 text-light/50 hover:text-light transition-all shadow-xl backdrop-blur-xl pointer-events-auto"
              title={userHiddenPanel ? "Open Panel" : "Hide Panel"}
            >
              {userHiddenPanel ? (
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
              )}
            </button>
          )}

          {/* Control Panel */}
          
          {currentView === "repo-select" && (
            <div className="w-full max-w-[500px] pointer-events-auto transition-all duration-700 mx-auto">
              <div className="rounded-2xl border border-light/10 bg-dark/90 backdrop-blur-xl shadow-2xl shadow-black/30 overflow-hidden">
                <div className="px-6 py-6 space-y-6">
                  <div className="space-y-1">
                    <h2 className="text-lg font-serif">Select Repository</h2>
                    <p className="text-xs text-light/40">Choose a repository to analyze and optimize its execution graph.</p>
                  </div>
                  
                  <div className="space-y-3">
                    <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
                      Repository
                    </label>

                    {/* Mode tabs */}
                    <div className="flex items-center gap-1 bg-light/5 rounded-lg p-1 w-fit">
                      <button
                        type="button"
                        onClick={() => setRepoMode("browse")}
                        className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                          repoMode === "browse"
                            ? "bg-light/15 text-light"
                            : "text-light/40 hover:text-light/70"
                        }`}
                      >
                        My Repositories
                      </button>
                      <button
                        type="button"
                        onClick={() => setRepoMode("url")}
                        className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                          repoMode === "url"
                            ? "bg-light/15 text-light"
                            : "text-light/40 hover:text-light/70"
                        }`}
                      >
                        Enter URL
                      </button>
                    </div>

                    {repoMode === "browse" && (
                      <div className="space-y-2">
                        <div className="relative">
                          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light/30" />
                          <Input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search repositories..."
                            className="bg-light/5 border-light/10 placeholder:text-light/25 pl-9"
                          />
                        </div>

                        <div className="max-h-52 overflow-y-auto rounded-lg border border-light/10 bg-light/[0.02]">
                          {fetchState === "loading" && (
                            <div className="p-3 space-y-2">
                              {Array.from({ length: 4 }).map((_, i) => (
                                <div key={i} className="flex items-center gap-3 p-2.5">
                                  <Skeleton className="w-6 h-6 rounded-full shrink-0 bg-light/10" />
                                  <div className="flex-1 space-y-1.5">
                                    <Skeleton className="h-3.5 w-40 bg-light/10" />
                                    <Skeleton className="h-2.5 w-24 bg-light/10" />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}

                          {fetchState === "error" && (
                            <div className="p-4 text-center">
                              <p className="text-xs text-accent-red">{fetchError}</p>
                              <button
                                onClick={() => setFetchState("idle")}
                                className="text-xs text-light/40 hover:text-light/70 mt-1"
                              >
                                Retry
                              </button>
                            </div>
                          )}

                          {fetchState === "loaded" && filtered.length === 0 && (
                            <div className="p-4 text-center text-xs text-light/30">
                              {search ? "No repositories match" : "No repositories found"}
                            </div>
                          )}

                          {fetchState === "loaded" &&
                            filtered.map((repo) => {
                              const isSelected = selectedRepo?.id === repo.id;
                              return (
                                <button
                                  key={repo.id}
                                  type="button"
                                  onClick={() => setSelectedRepo(isSelected ? null : repo)}
                                  className={`w-full text-left px-3 py-2.5 flex items-center gap-3 border-b border-light/5 last:border-b-0 transition-colors ${
                                    isSelected
                                      ? "bg-accent-blue/10"
                                      : "hover:bg-light/5"
                                  }`}
                                >
                                  <img
                                    src={repo.owner_avatar}
                                    alt={repo.owner}
                                    className="w-6 h-6 rounded-full shrink-0"
                                  />
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="text-xs font-medium text-light/80 truncate">
                                        {repo.full_name}
                                      </span>
                                      {repo.private && (
                                        <Badge
                                          variant="outline"
                                          className="text-[9px] px-1 py-0 h-3.5 border-light/15 text-light/40"
                                        >
                                          Private
                                        </Badge>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2 mt-0.5">
                                      {repo.language && (
                                        <span className="flex items-center gap-1 text-[10px] text-light/35">
                                          <span
                                            className="w-2 h-2 rounded-full inline-block"
                                            style={{
                                              backgroundColor:
                                                LANGUAGE_COLORS[repo.language] || "#8b8b8b",
                                            }}
                                          />
                                          {repo.language}
                                        </span>
                                      )}
                                      {repo.updated_at && (
                                        <span className="text-[10px] text-light/25">
                                          {formatRelativeTime(repo.updated_at)}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  {isSelected && (
                                    <svg
                                      className="w-4 h-4 text-accent-blue shrink-0"
                                      fill="none"
                                      viewBox="0 0 24 24"
                                      stroke="currentColor"
                                      strokeWidth={2}
                                    >
                                      <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        d="M5 13l4 4L19 7"
                                      />
                                    </svg>
                                  )}
                                </button>
                              );
                            })}
                        </div>
                      </div>
                    )}

                    {repoMode === "url" && (
                      <div className="space-y-1">
                        <Input
                          value={url}
                          onChange={(e) => {
                            setUrl(e.target.value);
                            if (urlError) setUrlError("");
                          }}
                          placeholder="https://github.com/owner/repository"
                          className="bg-light/5 border-light/10 placeholder:text-light/25"
                        />
                        {urlError && (
                          <p className="text-[10px] text-accent-red">{urlError}</p>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                
                <div className="px-6 py-4 border-t border-light/5 flex items-center justify-end">
                  {repoMode === "browse" ? (
                    <Button
                      onClick={handleBrowseAnalyze}
                      disabled={!selectedRepo || previewLoading}
                      className="bg-accent-blue hover:bg-accent-blue/80 text-light px-6 gap-2"
                    >
                      {previewLoading ? "Generating..." : "Generate Flowchart"}
                      <ArrowRight className="w-4 h-4" />
                    </Button>
                  ) : (
                    <Button
                      onClick={(e) => handleUrlSubmit(e as any)}
                      disabled={!url.trim() || previewLoading}
                      className="bg-accent-blue hover:bg-accent-blue/80 text-light px-6 gap-2"
                    >
                      {previewLoading ? "Generating..." : "Generate Flowchart"}
                      <ArrowRight className="w-4 h-4" />
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}

          {currentView !== "repo-select" && (
          <div
            className={`w-full max-w-[400px] pointer-events-auto transition-all duration-700 ease-[cubic-bezier(0.32,0.72,0,1)] flex flex-col justify-center translate-y-0 h-auto ${
              panelCollapsed
                ? "opacity-0 translate-x-12 scale-95 pointer-events-none absolute right-6"
                : userHiddenPanel
                ? "opacity-0 translate-x-[110%] absolute right-6"
                : "opacity-100 translate-x-0 relative right-0"
            }`}
          >
            <div className="rounded-2xl border border-light/10 bg-dark/90 backdrop-blur-xl shadow-2xl shadow-black/30 overflow-hidden">
              <div className="px-6 py-5 space-y-6">
                {/* 1. Node Selection UI */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
                      Target Nodes
                    </label>
                    <span className="text-[10px] font-mono text-light/40">
                      {selectedNodeIds.length} / {totalNodes} Selected
                    </span>
                  </div>

                  <div className="flex items-center gap-3 px-3 py-2.5 bg-light/5 rounded-lg border border-light/5 hover:bg-light/10 transition-colors cursor-pointer"
                       onClick={() => {
                         if (selectedNodeIds.length === totalNodes) {
                           setSelectedNodeIds([]);
                         } else {
                           setSelectedNodeIds(graphData?.nodes.map(n => n.id) ?? []);
                         }
                       }}>
                    <input
                      type="checkbox"
                      id="selectAllNodes"
                      checked={selectedNodeIds.length === totalNodes && totalNodes > 0}
                      readOnly
                      className="w-4 h-4 rounded border-light/20 bg-dark/50 text-accent-blue focus:ring-accent-blue/30 focus:ring-offset-dark pointer-events-none"
                    />
                    <label className="text-xs text-light/80 cursor-pointer user-select-none select-none pointer-events-none">
                      Select All / Optimize All Modules
                    </label>
                  </div>
                </div>

                {/* 2. Optimization Priority */}
                <div className="space-y-2">
                  <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
                    Optimization Priority
                  </label>
                  <div className="flex items-center gap-1 bg-light/5 rounded-lg p-1">
                    {BIAS_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setOptimizationBias(opt.value)}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs rounded-md transition-colors ${
                          optimizationBias === opt.value
                            ? "bg-light/15 text-light"
                            : "text-light/40 hover:text-light/60"
                        }`}
                      >
                        {opt.icon}
                        {opt.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-light/30 pl-1">
                    {BIAS_OPTIONS.find((o) => o.value === optimizationBias)?.description}
                  </p>
                </div>

                {/* 3. Analysis Mode */}
                <div className="space-y-2">
                  <label className="text-xs font-mono text-light/50 uppercase tracking-wider">
                    Analysis Mode
                  </label>
                  <div className="flex items-center gap-1 bg-light/5 rounded-lg p-1">
                    {ANALYSIS_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setAnalysisMode(opt.value)}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs rounded-md transition-colors ${
                          analysisMode === opt.value
                            ? "bg-light/15 text-light"
                            : "text-light/40 hover:text-light/60"
                        }`}
                      >
                        {opt.icon}
                        {opt.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-light/30 pl-1">
                    {ANALYSIS_OPTIONS.find((o) => o.value === analysisMode)?.description}
                  </p>
                </div>
              </div>

              {/* Action area */}
              <div className="px-6 py-4 border-t border-light/5 flex items-center justify-end">
                <Button
                  onClick={handleStartOptimization}
                  disabled={selectedNodeIds.length === 0}
                  className="bg-accent-blue hover:bg-accent-blue/80 text-light px-6 gap-2 w-full justify-between"
                >
                  <span className="flex-1 text-center">
                    {selectedNodeIds.length === totalNodes
                      ? "Optimize All Modules"
                      : `Optimize ${selectedNodeIds.length} Node${selectedNodeIds.length === 1 ? '' : 's'}`}
                  </span>
                  <ArrowRight className="w-4 h-4 right-0" />
                </Button>
              </div>
            </div>
          </div>
          )}

          {/* Running / Status overlay (shown when panel collapses) */}
          <div
            className={`absolute inset-0 flex flex-col items-center justify-center z-10 transition-all duration-700 ease-in-out ${
              panelCollapsed
                ? "opacity-100"
                : "opacity-0 pointer-events-none"
            }`}
          >
            <div className="text-center space-y-4">
              {isRunning && (
                <>
                  <div className="w-10 h-10 border-2 border-accent-blue/30 border-t-accent-blue rounded-full animate-spin mx-auto" />
                  <div>
                    <p className="text-sm font-medium text-light/80 capitalize">{phase}...</p>
                    <p className="text-xs text-light/40 mt-1 max-w-md font-mono">{currentMessage}</p>
                  </div>
                </>
              )}
              {phase === "error" && (
                <>
                  <p className="text-sm text-accent-red font-mono">{currentMessage}</p>
                  <button
                    onClick={handleReset}
                    className="text-xs text-accent-blue hover:underline font-mono"
                  >
                    &larr; Try again
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Bottom status bar */}
        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center justify-between z-20 bg-dark/80 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                phase === "idle"
                  ? "bg-accent-green"
                  : phase === "error"
                    ? "bg-accent-red"
                    : phase === "complete"
                      ? "bg-accent-green"
                      : "bg-accent-orange animate-pulse"
              }`}
            />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
          </div>
          <p className="font-mono text-[11px] text-light/30">
            {"● "}{statusText}
          </p>
          <span className="w-2 h-2 rounded-full bg-light/20" />
        </div>
      </div>
    </div>
  );
}
