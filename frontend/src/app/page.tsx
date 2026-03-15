"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useRef } from "react";
import AsciiBenchyScene from "@/components/benchy-ascii";
import * as htmlToImage from 'html-to-image';

export default function LandingPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [showArrow, setShowArrow] = useState(true);
  const logoRef = useRef<HTMLAnchorElement>(null);

  const exportLogo = () => {
    if (logoRef.current) {
      htmlToImage.toSvg(logoRef.current)
        .then((dataUrl) => {
          const link = document.createElement('a');
          link.download = 'benchy_logo.svg';
          link.href = dataUrl;
          link.click();
        })
        .catch((err) => {
          console.error('oops, something went wrong!', err);
        });
    }
  };

  useEffect(() => {
    if (session) {
      router.push("/dashboard");
    }
  }, [session, router]);

  return (
    <div className="h-screen bg-light p-3 sm:p-4 flex flex-col">
      {/* Dark interior panel — fills the frame, rounded inside */}
      <div className="flex-1 min-h-0 bg-dark text-light rounded-xl flex flex-col overflow-hidden relative">
        {/* Top nav — pinned */}
        <nav className="shrink-0 flex items-center justify-between px-6 sm:px-10 py-4 border-b border-light/10">
          <a
            ref={logoRef}
            onClick={(e) => { e.preventDefault(); exportLogo(); }}
            href="/"
            className="flex items-center gap-2 hover:opacity-80 transition-opacity text-4xl"
          >
            <div className="h-8 w-8 bg-linear-to-b from-light via-light/80 to-light/40" style={{ maskImage: 'url(/images/benchy_light.svg)', maskSize: 'contain', maskRepeat: 'no-repeat', maskPosition: 'center', WebkitMaskImage: 'url(/images/benchy_light.svg)', WebkitMaskSize: 'contain', WebkitMaskRepeat: 'no-repeat', WebkitMaskPosition: 'center' }} />
            <span className="font-serif font-bold bg-linear-to-b from-light via-light/80 to-light/40 bg-clip-text text-transparent">Benchy</span>
          </a>
          <div className="flex items-center gap-6">
            <a
              href="/debug"
              className="text-xs font-mono text-light/40 hover:text-light/70 transition-colors"
            >
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
        <div
          className="flex-1 min-h-0 overflow-y-auto relative custom-scrollbar scroll-smooth"
          onScroll={(e) => setShowArrow(e.currentTarget.scrollTop < 50)}
        >
          {/* Background — spinning benchy */}
          <div className="absolute top-0 left-0 w-full h-[calc(100vh-8rem)] pointer-events-none opacity-40">
            <AsciiBenchyScene color="#faefe050" />
          </div>

          <div className="relative z-10 flex flex-col">
            {/* Hero Section */}
            <div className="relative min-h-[calc(100vh-8rem)] flex items-center justify-center px-6 sm:px-10 py-12 pb-32">
              <div className="max-w-2xl text-center space-y-12">
                <div className="space-y-8">
                  <div>
                    <h1 className="font-serif font-bold sm:text-8xl text-7xl leading-[1.1] tracking-tight pb-2 bg-linear-to-b from-light via-light/80 to-light/40 bg-clip-text text-transparent">
                      Benchy
                    </h1>
                  </div>
                  <p className="text-light/50 text-sm sm:text-base max-w-md mx-auto leading-relaxed">
                    AI-powered performance analysis and optimization for your
                    codebase.
                  </p>
                </div>

                <div className="flex flex-col items-center gap-8">
                  {/* Action Buttons */}
                  <div className="flex flex-col sm:flex-row items-center gap-4 relative z-50">
                    <button
                      type="button"
                      onClick={() =>
                        signIn("github", { callbackUrl: "/dashboard" })
                      }
                      disabled={status === "loading"}
                      className="group flex items-center gap-3 font-mono text-sm bg-light text-dark px-6 py-3 rounded hover:bg-light/90 transition-colors cursor-pointer"
                    >
                      <svg
                        className="w-5 h-5 pointer-events-none"
                        fill="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                      </svg>
                      <span>Sign in with GitHub</span>
                    </button>
                    <a
                      href="#demo"
                      className="font-mono text-sm text-light/70 hover:text-light transition-colors px-6 py-3 border border-light/20 rounded hover:border-light/40"
                    >
                      Learn More
                    </a>
                  </div>

                  {/* Supported Languages */}
                  <div className="flex flex-col items-center gap-3">
                    <p className="text-[11px] font-bold text-light/40 uppercase tracking-widest">
                      Supported languages
                    </p>
                    <div className="flex items-center gap-6 text-light/30">
                      <span className="font-mono text-sm hover:text-light/60 transition-colors cursor-default">
                        Python
                      </span>
                      <span className="font-mono text-sm hover:text-light/60 transition-colors cursor-default">
                        JavaScript
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Visual Proof / Demo Section (Below Fold) */}
            <div
              id="demo"
              className="w-full max-w-5xl mx-auto px-6 sm:px-10 py-16 pb-32"
            >
              <div className="flex flex-col gap-24">
                {/* How it Works section */}
                <div className="space-y-12 pb-24 text-light/80">
                  <div className="text-center space-y-4">
                    <h2 className="font-serif font-bold text-4xl sm:text-5xl bg-linear-to-b from-light via-light/80 to-light/40 bg-clip-text text-transparent
">
                      How it Works
                    </h2>
                    <p className="font-mono text-xs text-light/40 uppercase tracking-widest">
                      The Benchy Architecture
                    </p>
                  </div>

                  <div className="grid md:grid-cols-2 gap-12 sm:gap-16 max-w-4xl mx-auto items-start">
                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-accent-blue/20 font-mono text-s text-accent-blue">
                          1
                        </span>
                        <h3 className="font-serif text-3xl font-bold pl-2 text-accent-blue">
                          Job Submission
                        </h3>
                      </div>
                      <p className="text-base text-light/60 leading-relaxed">
                        Submit a <strong className="text-light/80">GitHub URL</strong> via the dashboard, or trigger Benchy
                        right from the <strong className="text-light/80">VS Code extension</strong>. The extension packages
                        up local files (respecting <strong className="text-light/80">.gitignore</strong>) and sends them
                        to the <strong className="text-light/80">FastAPI backend</strong>.
                      </p>
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-accent-purple/20 font-mono text-s text-accent-purple">
                          2
                        </span>
                        <h3 className="font-serif text-3xl font-bold pl-2 text-accent-purple">
                          Agentic Pipeline
                        </h3>
                      </div>
                      <p className="text-base text-light/60 leading-relaxed">
                        Built on top of <strong className="text-light/80">Railtracks by Railtown</strong>, the overarching
                        AI agent converts source code into an <strong className="text-light/80">Abstract Syntax
                        Tree (AST)</strong> to map its structure. It then executes the
                        code dynamically with injected <strong className="text-light/80">profiling tools</strong> to
                        identify actual <strong className="text-light/80">algorithmic bottlenecks</strong>.
                      </p>
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-accent-green/20 font-mono text-s text-accent-green">
                          3
                        </span>
                        <h3 className="font-serif text-3xl font-bold pl-2 text-accent-green">
                          Optimization
                        </h3>
                      </div>
                      <p className="text-base text-light/60 leading-relaxed">
                        Using real <strong className="text-light/80">runtime data</strong> and <strong className="text-light/80">flame graphs</strong> from the
                        sandbox environment, <strong className="text-light/80">Gemini</strong> rewrites the slow functions.
                        The code is <strong className="text-light/80">re-run and verified</strong> to ensure exact
                        functionality while running significantly faster.
                      </p>
                    </div>
                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-accent-orange/20 font-mono text-s text-accent-orange">
                          4
                        </span>
                        <h3 className="font-serif text-3xl font-bold pl-2 text-accent-orange">
                          Code Delivery
                        </h3>
                      </div>
                      <p className="text-base text-light/60 leading-relaxed">
                        <strong className="text-light/80">Live telemetry</strong> streams the execution directly to your
                        browser. Once finalized, <strong className="text-light/80">radar charts</strong> compare the
                        baseline to the optimized code, rendering a <strong className="text-light/80">side-by-side
                        IDE-style diff</strong> that you can instantly apply back into
                        your IDE.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Scroll Indicator - Always anchored to viewport bottom */}
        <div
          className="absolute z-20 bottom-24 left-1/2 -translate-x-1/2 animate-bounce hidden sm:block transition-opacity duration-500 pointer-events-none"
          style={{ opacity: showArrow ? 0.4 : 0 }}
        >
          <svg
            className="w-6 h-6 text-light"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 14l-7 7m0 0l-7-7m7 7V3"
            />
          </svg>
        </div>

        {/* Terminal status bar — pinned */}
        <div className="shrink-0 border-t border-light/10 px-6 sm:px-10 py-3 flex items-center bg-dark z-20">
          <p className="font-mono text-[11px] text-light/30">
            [✓] all systems nominal · welcome to benchy
          </p>
        </div>
      </div>
    </div>
  );
}
