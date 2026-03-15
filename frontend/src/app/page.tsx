"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import AsciiBenchyScene from "@/components/benchy-ascii";

export default function LandingPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session) {
      router.push("/dashboard");
    }
  }, [session, router]);

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      {/* Dark interior panel — fills the frame, rounded inside */}
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden">
        {/* Top nav — pinned */}
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity text-3xl">
            <img src="/images/benchy_light.svg" alt="Benchy" className="h-8"/>
            <span className="font-serif">Benchy</span>
          </a>
          <div className="flex items-center gap-6">
            <a href="/debug" className="text-xs font-mono text-light/40 hover:text-light/70 transition-colors">
              /debug
            </a>
            <button
              onClick={() => signIn("github", { callbackUrl: "/dashboard" })}
              disabled={status === "loading"}
              className="text-xs font-mono text-light/60 hover:text-light transition-colors"
            >
              sign in →
            </button>
          </div>
        </nav>

        {/* Content area with benchy background */}
        <div className="flex-1 min-h-0 relative">
          {/* Background — spinning benchy */}
          <div className="absolute inset-0 pointer-events-none">
            <AsciiBenchyScene color="#faefe020" />
          </div>

          {/* Foreground — centered text */}
          <div className="relative z-10 h-full flex items-center justify-center px-6 sm:px-10">
            <div className="max-w-xl text-center space-y-8">
              <h1 className="font-serif sm:text-8xl text-9xl leading-[0.9] tracking-tight">
                Benchy
              </h1>
              <p className="text-light/50 text-sm sm:text-base max-w-md mx-auto leading-relaxed">
                AI-powered performance analysis and optimization for your codebase.
              </p>
              <button
                onClick={() => signIn("github", { callbackUrl: "/dashboard" })}
                disabled={status === "loading"}
                className="group inline-flex items-center gap-3 font-mono text-sm text-light/70 hover:text-light transition-colors"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                </svg>
                <span>Sign in with GitHub</span>
                <span className="text-light/30 group-hover:text-light/60 transition-colors">→</span>
              </button>
            </div>
          </div>
        </div>

        {/* Terminal status bar — pinned */}
        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-accent-green" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
            <span className="w-2.5 h-2.5 rounded-full bg-light/20" />
          </div>
          <p className="font-mono text-[11px] text-light/30">
            ● [✓] all systems nominal · welcome to benchy
          </p>
          <span className="w-2 h-2 rounded-full bg-light/20" />
        </div>
      </div>
    </div>
  );
}
