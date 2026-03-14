"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function LandingPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session) {
      router.push("/dashboard");
    }
  }, [session, router]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="max-w-2xl text-center space-y-8">
        <div className="space-y-4">
          <h1 className="text-5xl font-bold tracking-tight">
            Code<span className="text-blue-500">Mark</span>
          </h1>
          <p className="text-xl text-neutral-400">
            AI-powered performance analysis and optimization for your codebase
          </p>
        </div>

        <div className="space-y-3 text-sm text-neutral-500 max-w-md mx-auto">
          <div className="flex items-center gap-3 text-left">
            <div className="w-8 h-8 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center text-xs font-mono shrink-0">
              1
            </div>
            <span>Connect your GitHub repository</span>
          </div>
          <div className="flex items-center gap-3 text-left">
            <div className="w-8 h-8 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center text-xs font-mono shrink-0">
              2
            </div>
            <span>AI agent analyzes AST, profiles bottlenecks in a sandbox</span>
          </div>
          <div className="flex items-center gap-3 text-left">
            <div className="w-8 h-8 rounded-full bg-blue-500/10 text-blue-500 flex items-center justify-center text-xs font-mono shrink-0">
              3
            </div>
            <span>Get optimized code with a before/after CodeMark score</span>
          </div>
        </div>

        <Button
          size="lg"
          onClick={() => signIn("github", { callbackUrl: "/dashboard" })}
          disabled={status === "loading"}
          className="bg-white text-black hover:bg-neutral-200 font-medium px-8"
        >
          <svg className="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          Sign in with GitHub
        </Button>
      </div>

      <div className="mt-12 w-full max-w-md space-y-4 border border-neutral-800 rounded-lg p-6">
        <p className="text-xs uppercase tracking-widest text-neutral-500 mb-4">Font Test</p>
        <div className="space-y-1">
          <p className="text-xs text-neutral-500">font-sans (Inter):</p>
          <p className="font-sans text-2xl">The quick brown fox jumps over the lazy dog</p>
        </div>
        <div className="space-y-1">
          <p className="text-xs text-neutral-500">font-serif (Junicode Bold Italic):</p>
          <p className="font-serif text-2xl">The quick brown fox jumps over the lazy dog</p>
        </div>
        <div className="space-y-1">
          <p className="text-xs text-neutral-500">font-mono (Geist Mono):</p>
          <p className="font-mono text-2xl">The quick brown fox jumps over the lazy dog</p>
        </div>
      </div>

      <footer className="absolute bottom-8 text-xs text-neutral-600">
        Built with LangGraph + Gemini + E2B
      </footer>
    </div>
  );
}
