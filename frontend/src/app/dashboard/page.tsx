"use client";

import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { RepoInput } from "@/components/repo-input";
import { ProgressStepper } from "@/components/progress-stepper";
import { startAnalysis, streamJob } from "@/lib/api";
import { toast } from "sonner";
import { GlobalFooterPill } from "@/components/global-footer-pill";

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
  const [error, setError] = useState<string | null>(null);

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
    async (repoUrl: string, optimizationBias: string = "balanced", fastMode: boolean = false) => {
      const token = (session as any)?.accessToken;
      if (!token) {
        toast.error("GitHub token not available. Please sign in again.");
        return;
      }

      setPhase("analyzing");
      setMessages([]);
      setError(null);

      try {
        const { job_id } = await startAnalysis(repoUrl, token, optimizationBias, fastMode);

        streamJob(
          job_id,
          (event) => {
            if (event.event === "progress" && event.data) {
              const { node, message } = event.data;
              setMessages((prev) => [
                ...prev,
                { node, message, timestamp: Date.now() },
              ]);
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
              router.push("/job/" + job_id);
            }
          },
          (err) => {
            setPhase("error");
            setError(err.message);
            toast.error(err.message);
          },
          () => {
            // onComplete fallback — redirect if not already in error
            router.push("/job/" + job_id);
          }
        );
      } catch (err: any) {
        setPhase("error");
        setError(err.message || "Failed to start analysis");
        toast.error(err.message || "Failed to start analysis");
      }
    },
    [session, router]
  );

  const handleRetry = () => {
    setPhase("idle");
    setMessages([]);
    setError(null);
  };

  if (status === "loading") {
    return (
      <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
        <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex items-center justify-center">
          <span className="animate-pulse text-light/40 font-mono text-sm">loading…</span>
        </div>
      </div>
    );
  }

  const isRunning = phase !== "idle" && phase !== "error";
  const lastMessage = messages.length > 0 ? messages[messages.length - 1].message : "";

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden">
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity text-3xl">
            <div className="h-8 w-8 bg-linear-to-b from-light via-light/90 to-light/50" style={{ maskImage: 'url(/images/benchy_light.svg)', maskSize: 'contain', maskRepeat: 'no-repeat', maskPosition: 'center', WebkitMaskImage: 'url(/images/benchy_light.svg)', WebkitMaskSize: 'contain', WebkitMaskRepeat: 'no-repeat', WebkitMaskPosition: 'center' }} />
            <span className="font-serif font-bold pl-1 pb-1 translate-y-1 bg-linear-to-b from-light via-light/90 to-light/50 bg-clip-text text-transparent">Benchy</span>
          </a>
          <div className="flex items-center gap-6">
            <span className="text-xs font-mono text-light/40">
              {session?.user?.name}
            </span>
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
            {phase === "idle" && (
              <>
                <RepoInput
                  onAnalyze={handleAnalyze}
                  isLoading={false}
                  accessToken={(session as any)?.accessToken ?? null}
                />
                <div className="text-center py-20">
                  <p className="text-lg text-light/30">Select a repository to get started</p>
                  <p className="text-sm mt-2 text-light/20">
                    We&apos;ll analyze the codebase, benchmark performance, and optimize bottlenecks
                  </p>
                </div>
              </>
            )}

            {isRunning && (
              <div className="flex flex-col items-center justify-center py-20">
                <ProgressStepper phase={phase} currentMessage={lastMessage} />
              </div>
            )}

            {phase === "error" && (
              <div className="flex flex-col items-center justify-center py-20 gap-4">
                <p className="text-accent-red font-mono text-sm">{error}</p>
                <button
                  onClick={handleRetry}
                  className="text-sm font-mono text-accent-blue hover:underline"
                >
                  ← Try again
                </button>
              </div>
            )}
          </div>
        </div>
        
        <GlobalFooterPill />
      </div>
    </div>
  );
}
