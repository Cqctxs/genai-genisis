"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Check } from "lucide-react";

type Phase =
  | "idle"
  | "analyzing"
  | "benchmarking"
  | "optimizing"
  | "re-benchmarking"
  | "scoring"
  | "complete"
  | "error";

interface ProgressStepperProps {
  phase: Phase;
  currentMessage: string;
}

const STEPS: { key: Phase; label: string }[] = [
  { key: "analyzing", label: "Analyzing" },
  { key: "benchmarking", label: "Benchmarking" },
  { key: "optimizing", label: "Optimizing" },
  { key: "scoring", label: "Scoring" },
];

export function ProgressStepper({ phase, currentMessage }: ProgressStepperProps) {
  const activeIndex = STEPS.findIndex((s) => s.key === phase || (phase === "re-benchmarking" && s.key === "optimizing"));
  const isComplete = phase === "complete";
  const isError = phase === "error";

  const startTime = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (isComplete || isError) return;
    const id = setInterval(() => setElapsed(Date.now() - startTime.current), 1000);
    return () => clearInterval(id);
  }, [isComplete, isError]);

  const mins = Math.floor(elapsed / 60000);
  const secs = Math.floor((elapsed % 60000) / 1000);
  const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

  return (
    <div className="space-y-8">
      {/* Elapsed time */}
      <p className="text-center text-xs font-mono text-light/30">{timeStr} elapsed</p>
      {/* Horizontal stepper */}
      <div className="flex items-center justify-center gap-0">
        {STEPS.map((step, i) => {
          const isDone = isComplete || i < activeIndex;
          const isActive = !isComplete && !isError && i === activeIndex;
          const isUpcoming = !isDone && !isActive;

          return (
            <div key={step.key} className="flex items-center">
              {i > 0 && (
                <div
                  className={`h-px w-12 sm:w-20 transition-colors duration-500 ${
                    isDone ? "bg-accent-blue" : "bg-light/10"
                  }`}
                />
              )}
              <div className="flex flex-col items-center gap-2">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-mono transition-all duration-500 ${
                    isDone
                      ? "bg-accent-blue text-light"
                      : isActive
                      ? "bg-accent-blue/20 text-accent-blue ring-2 ring-accent-blue/50"
                      : isError && i === activeIndex
                      ? "bg-accent-red/20 text-accent-red ring-2 ring-accent-red/50"
                      : "bg-light/5 text-light/20"
                  }`}
                >
                  {isDone ? (
                    <Check className="w-4 h-4" />
                  ) : isActive ? (
                    <span className="w-2 h-2 rounded-full bg-accent-blue animate-pulse" />
                  ) : (
                    <span>{i + 1}</span>
                  )}
                </div>
                <span
                  className={`text-xs font-mono transition-colors duration-300 ${
                    isDone
                      ? "text-accent-blue"
                      : isActive
                      ? "text-light"
                      : isUpcoming
                      ? "text-light/20"
                      : "text-light/40"
                  }`}
                >
                  {step.label}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Current message display */}
      {currentMessage && (
        <div className="flex items-center justify-center gap-3 px-4 py-3 rounded-lg bg-light/5 border border-light/10 max-w-xl mx-auto">
          {!isComplete && !isError && (
            <Loader2 className="w-4 h-4 animate-spin text-accent-blue shrink-0" />
          )}
          {isComplete && <Check className="w-4 h-4 text-accent-green shrink-0" />}
          <p className="text-sm text-light/60 font-mono truncate">{currentMessage}</p>
        </div>
      )}
    </div>
  );
}
