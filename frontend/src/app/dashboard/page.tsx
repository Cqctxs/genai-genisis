"use client";

import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { RepoInput } from "@/components/repo-input";
import { LiveTelemetry } from "@/components/live-telemetry";
import { PerformanceGraph } from "@/components/performance-graph";
import { ScoreDashboard } from "@/components/score-dashboard";
import { PullRequestView } from "@/components/comparison-view";
import { ErrorBoundary } from "@/components/error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { startAnalysis, streamJob, getResults, type JobResult } from "@/lib/api";
import { toast } from "sonner";

type Phase =
  | "idle"
  | "analyzing"
  | "benchmarking"
  | "optimizing"
  | "re-benchmarking"
  | "scoring"
  | "complete"
  | "error";

interface ProgressMessage {
  node: string;
  message: string;
  timestamp: number;
}

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("idle");
  const [messages, setMessages] = useState<ProgressMessage[]>([]);
  const [results, setResults] = useState<JobResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("telemetry");

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  const nodeToPhase: Record<string, Phase> = {
    clone: "analyzing",
    parse_ast: "analyzing",
    analyze: "analyzing",
    generate_benchmarks: "benchmarking",
    run_benchmarks: "benchmarking",
    visualize: "benchmarking",
    optimize: "optimizing",
    rerun_benchmarks: "re-benchmarking",
    report: "scoring",
    create_pr: "scoring",
    cleanup: "scoring",
  };

  const handleAnalyze = useCallback(
    async (repoUrl: string, optimizationBias: string = "balanced") => {
      const token = (session as any)?.accessToken;
      if (!token) {
        toast.error("GitHub token not available. Please sign in again.");
        return;
      }

      setPhase("analyzing");
      setMessages([]);
      setResults(null);

      try {
        const { job_id } = await startAnalysis(repoUrl, token, optimizationBias);
        setJobId(job_id);

        streamJob(
          job_id,
          (event) => {
            if (event.event === "progress" && event.data) {
              const { node, message } = event.data;
              setMessages((prev) => [
                ...prev,
                { node, message, timestamp: Date.now() },
              ]);
              if (node && nodeToPhase[node]) {
                setPhase(nodeToPhase[node]);
              }
            }
            if (event.event === "complete") {
              setPhase("complete");
              getResults(job_id).then((r) => {
                setResults(r);
                setActiveTab("results");
              });
            }
          },
          (error) => {
            setPhase("error");
            toast.error(error.message);
          },
          () => {
            if (phase !== "error") {
              getResults(job_id)
                .then((r) => {
                  setResults(r);
                  setPhase("complete");
                  setActiveTab("results");
                })
                .catch(() => {});
            }
          }
        );
      } catch (err: any) {
        setPhase("error");
        toast.error(err.message || "Failed to start analysis");
      }
    },
    [session, phase]
  );

  const statusText =
    phase === "idle"
      ? "● [✓] ready · select a repository"
      : phase === "complete"
      ? "● [✓] analysis complete"
      : phase === "error"
      ? "● [✗] error encountered"
      : `● [◎] ${phase}…`;

  if (status === "loading") {
    return (
      <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
        <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex items-center justify-center">
          <span className="animate-pulse text-light/40 font-mono text-sm">loading…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden">
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <a href="/" className="font-serif text-xl hover:text-light/80 transition-colors">
            Benchy
          </a>
          <div className="flex items-center gap-6">
            <span className="text-xs font-mono text-light/40">
              {session?.user?.name}
            </span>
            <a
              href="/debug"
              className="text-xs font-mono text-light/40 hover:text-light/70 transition-colors"
            >
              /debug
            </a>
            <button
              onClick={() => signOut({ callbackUrl: "/" })}
              className="text-xs font-mono text-light/60 hover:text-light transition-colors"
            >
              sign out →
            </button>
          </div>
        </nav>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 sm:px-10 py-8">
          <div className="max-w-7xl mx-auto w-full space-y-6">
            <RepoInput
              onAnalyze={handleAnalyze}
              isLoading={phase !== "idle" && phase !== "complete" && phase !== "error"}
              accessToken={(session as any)?.accessToken ?? null}
            />

            {phase !== "idle" && (
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList className="bg-light/5 border border-light/10">
                  <TabsTrigger value="telemetry">Live Telemetry</TabsTrigger>
                  <TabsTrigger value="graph">Performance Graph</TabsTrigger>
                  <TabsTrigger value="results" disabled={!results}>
                    Results
                  </TabsTrigger>
                  <TabsTrigger value="pr" disabled={!results}>
                    Pull Request
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="telemetry" className="mt-4">
                  <ErrorBoundary>
                    <LiveTelemetry phase={phase} messages={messages} />
                  </ErrorBoundary>
                </TabsContent>

                <TabsContent value="graph" className="mt-4">
                  <ErrorBoundary>
                    <PerformanceGraph graphData={results?.graph_data ?? null} />
                  </ErrorBoundary>
                </TabsContent>

                <TabsContent value="results" className="mt-4">
                  <ErrorBoundary>
                    {results?.comparison && (
                      <ScoreDashboard comparison={results.comparison} />
                    )}
                  </ErrorBoundary>
                </TabsContent>

                <TabsContent value="pr" className="mt-4">
                  <ErrorBoundary>
                    {results && (
                      <PullRequestView
                        prUrl={results.pr_url ?? ""}
                        optimizedFiles={results.optimized_files ?? {}}
                        comparison={results.comparison ?? null}
                        prStatus={results.pr_status}
                        prError={results.pr_error}
                      />
                    )}
                  </ErrorBoundary>
                </TabsContent>
              </Tabs>
            )}

            {phase === "idle" && (
              <div className="text-center py-20">
                <p className="text-lg text-light/30">Select a repository to get started</p>
                <p className="text-sm mt-2 text-light/20">
                  We&apos;ll analyze the codebase, benchmark performance, and optimize bottlenecks
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                phase === "idle" || phase === "complete"
                  ? "bg-accent-green"
                  : phase === "error"
                  ? "bg-accent-red"
                  : "bg-accent-orange animate-pulse"
              }`}
            />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
          </div>
          <p className="font-mono text-[11px] text-light/30">{statusText}</p>
          <span className="w-2 h-2 rounded-full bg-light/20" />
        </div>
      </div>
    </div>
  );
}
