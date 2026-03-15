"use client";

import { useParams, useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
// @ts-expect-error - react-syntax-highlighter doesn't have type definitions
import SyntaxHighlighter from "react-syntax-highlighter";
// @ts-expect-error - react-syntax-highlighter doesn't have type definitions
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs";
import { PerformanceGraph } from "@/components/performance-graph";
import { ScoreDashboard } from "@/components/score-dashboard";
import { PullRequestView } from "@/components/comparison-view";
import { ErrorBoundary } from "@/components/error-boundary";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getResults, type JobResult } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function JobResultsPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: session, status } = useSession();
  const router = useRouter();

  const [results, setResults] = useState<JobResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("results");

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/");
    }
  }, [status, router]);

  useEffect(() => {
    if (!jobId) return;

    setLoading(true);
    getResults(jobId)
      .then((r) => {
        setResults(r);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load results");
        setLoading(false);
      });
  }, [jobId]);

  if (status === "loading" || loading) {
    return (
      <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
        <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col items-center justify-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-accent-blue" />
          <span className="text-light/40 font-mono text-sm">Loading results…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
        <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col items-center justify-center gap-4">
          <p className="text-accent-red font-mono text-sm">{error}</p>
          <button
            onClick={() => router.push("/dashboard")}
            className="text-sm font-mono text-accent-blue hover:underline"
          >
            ← Back to dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden">
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity text-3xl">
            <img src="/images/benchy_light.svg" alt="Benchy" className="h-8"/>
            <span className="font-serif">Benchy</span>
          </a>
          <div className="flex items-center gap-6">
            <span className="text-xs font-mono text-light/40">
              {session?.user?.name}
            </span>
            <button
              onClick={() => router.push("/dashboard")}
              className="text-xs font-mono text-light/60 hover:text-light transition-colors"
            >
              ← new analysis
            </button>
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
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="bg-light/5 border border-light/10">
                <TabsTrigger value="graph">Performance Graph</TabsTrigger>
                <TabsTrigger value="results" disabled={!results?.comparison}>
                  Results
                </TabsTrigger>
                <TabsTrigger value="benchmarks" disabled={!results?.benchmark_details?.length}>
                  Benchmarks
                </TabsTrigger>
                <TabsTrigger value="pr" disabled={!results}>
                  Pull Request
                </TabsTrigger>
              </TabsList>

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

              <TabsContent value="benchmarks" className="mt-4">
                <ErrorBoundary>
                  {results?.benchmark_details && results.benchmark_details.length > 0 ? (
                    <div className="space-y-4">
                      {results.benchmark_details.map((detail, idx) => (
                        <div key={idx} className="border border-light/10 rounded-lg p-4 bg-light/5 space-y-3">
                          <div className="flex items-start justify-between">
                            <div>
                              <h3 className="font-mono text-sm font-semibold text-light">{detail.function_name}</h3>
                              <p className="text-xs text-light/60 mt-1">{detail.file}</p>
                            </div>
                            <div className={`text-sm font-medium px-2 py-1 rounded ${detail.speedup_factor >= 1 ? 'bg-accent-green/20 text-accent-green' : 'bg-accent-red/20 text-accent-red'}`}>
                              {detail.speedup_factor >= 1
                                ? `${detail.speedup_factor.toFixed(1)}x faster`
                                : `${(1 / detail.speedup_factor).toFixed(1)}x slower`}
                            </div>
                          </div>

                          {detail.summary && (
                            <div className="space-y-1">
                              <p className="text-xs text-light/50">What this benchmark tests:</p>
                              <p className="text-sm text-light/80 border-l-2 border-light/20 pl-3 py-1">
                                {detail.summary}
                              </p>
                            </div>
                          )}

                          <div className="grid grid-cols-2 gap-3 text-xs">
                            <div className="bg-light/5 p-2 rounded">
                              <span className="text-light/60">Before</span>
                              <div className="text-light mt-1">
                                <p>{detail.before_time_ms.toFixed(2)}ms</p>
                                <p className="text-light/60">{detail.before_memory_mb.toFixed(1)}MB</p>
                              </div>
                            </div>
                            <div className="bg-light/5 p-2 rounded">
                              <span className="text-light/60">After</span>
                              <div className="text-light mt-1">
                                <p>{detail.after_time_ms.toFixed(2)}ms</p>
                                <p className="text-light/60">{detail.after_memory_mb.toFixed(1)}MB</p>
                              </div>
                            </div>
                          </div>

                          <div className="space-y-2">
                            <p className="text-xs text-light/50">Benchmark code ({detail.language}):</p>
                            <div className="rounded overflow-hidden max-h-96">
                              <SyntaxHighlighter
                                language={detail.language === "javascript" || detail.language === "typescript" ? "javascript" : "python"}
                                style={atomOneDark}
                                customStyle={{
                                  margin: 0,
                                  padding: "12px",
                                  fontSize: "11px",
                                  lineHeight: "1.5",
                                  maxHeight: "400px",
                                  overflow: "auto",
                                }}
                              >
                                {detail.script_content}
                              </SyntaxHighlighter>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-12 text-light/40">
                      <p>No benchmark details available</p>
                    </div>
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
          </div>
        </div>

        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-accent-green" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
          </div>
          <p className="font-mono text-[11px] text-light/30">● [✓] analysis complete</p>
          <span className="w-2 h-2 rounded-full bg-light/20" />
        </div>
      </div>
    </div>
  );
}
