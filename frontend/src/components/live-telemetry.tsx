"use client";

import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

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

interface LiveTelemetryProps {
  phase: Phase;
  messages: ProgressMessage[];
}

const PHASES: { key: Phase; label: string }[] = [
  { key: "analyzing", label: "Analyzing Codebase" },
  { key: "benchmarking", label: "Running Baseline" },
  { key: "optimizing", label: "Optimizing Code" },
  { key: "re-benchmarking", label: "Re-benchmarking" },
  { key: "scoring", label: "Scoring" },
  { key: "complete", label: "Complete" },
];

export function LiveTelemetry({ phase, messages }: LiveTelemetryProps) {
  const consoleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [messages]);

  const currentPhaseIndex = PHASES.findIndex((p) => p.key === phase);

  return (
    <div className="space-y-4">
      {/* Phase stepper */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardContent className="py-4">
          <div className="flex items-center gap-2">
            {PHASES.map((p, i) => {
              const isActive = p.key === phase;
              const isDone = i < currentPhaseIndex;
              const isError = phase === "error";

              return (
                <div key={p.key} className="flex items-center gap-2">
                  {i > 0 && (
                    <div
                      className={`h-px w-6 ${
                        isDone ? "bg-blue-500" : "bg-neutral-700"
                      }`}
                    />
                  )}
                  <Badge
                    variant={isActive ? "default" : "outline"}
                    className={`text-xs whitespace-nowrap ${
                      isDone
                        ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
                        : isActive && !isError
                        ? "bg-blue-600 text-white animate-pulse"
                        : isError && isActive
                        ? "bg-red-600 text-white"
                        : "text-neutral-500 border-neutral-700"
                    }`}
                  >
                    {isDone && "✓ "}
                    {p.label}
                  </Badge>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Console output */}
      <Card className="bg-neutral-900 border-neutral-800">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-neutral-400 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            Live Console
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div
            ref={consoleRef}
            className="bg-neutral-950 rounded-lg p-4 font-mono text-xs h-64 overflow-y-auto space-y-1"
          >
            {messages.length === 0 ? (
              <p className="text-neutral-600">Waiting for output...</p>
            ) : (
              messages.map((msg, i) => (
                <div key={i} className="flex gap-3">
                  <span className="text-neutral-600 shrink-0">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="text-blue-400 shrink-0">[{msg.node}]</span>
                  <span className="text-neutral-300">{msg.message}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
