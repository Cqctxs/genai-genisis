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
      <Card className="bg-light/5">
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
                        isDone ? "bg-accent-blue" : "bg-light/15"
                      }`}
                    />
                  )}
                  <Badge
                    variant={isActive ? "default" : "outline"}
                    className={`text-xs whitespace-nowrap ${
                      isDone
                        ? "bg-accent-blue/20 text-accent-blue border-accent-blue/30"
                        : isActive && !isError
                        ? "bg-accent-blue text-light animate-pulse"
                        : isError && isActive
                        ? "bg-accent-red text-light"
                        : "text-light/40 border-light/15"
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

      <Card className="bg-light/5">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-light/50 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
            Live Console
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div
            ref={consoleRef}
            className="bg-dark rounded-lg p-4 font-mono text-xs h-64 overflow-y-auto space-y-1"
          >
            {messages.length === 0 ? (
              <p className="text-light/30">Waiting for output...</p>
            ) : (
              messages.map((msg, i) => (
                <div key={i} className="flex gap-3">
                  <span className="text-light/30 shrink-0">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="text-accent-blue shrink-0">[{msg.node}]</span>
                  <span className="text-light/70">{msg.message}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
