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
import { Button } from "@/components/ui/button";
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
    async (repoUrl: string) => {
      const token = (session as any)?.accessToken;
      if (!token) {
        toast.error("GitHub token not available. Please sign in again.");
        return;
      }

      setPhase("analyzing");
      setMessages([]);
      setResults(null);

      try {
        const { job_id } = await startAnalysis(repoUrl, token);
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

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse text-neutral-500">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-neutral-800 px-6 py-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold tracking-tight">
          Benchy
        </h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-neutral-500">
            {session?.user?.name}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => signOut({ callbackUrl: "/" })}
          >
            Sign out
          </Button>
        </div>
      </header>

      <main className="flex-1 p-6 max-w-7xl mx-auto w-full space-y-6">
        <RepoInput
          onAnalyze={handleAnalyze}
          isLoading={phase !== "idle" && phase !== "complete" && phase !== "error"}
          accessToken={(session as any)?.accessToken ?? null}
        />

        {phase !== "idle" && (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="bg-neutral-900 border border-neutral-800">
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
          <div className="text-center py-20 text-neutral-600">
            <p className="text-lg">Select a repository to get started</p>
            <p className="text-sm mt-2">
              We&apos;ll analyze the codebase, benchmark performance, and optimize bottlenecks
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
