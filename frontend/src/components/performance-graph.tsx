"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { GraphData } from "@/lib/api";

interface PerformanceGraphProps {
  graphData: GraphData | null;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "var(--color-accent-red)",
  high: "var(--color-accent-orange)",
  medium: "var(--color-accent-purple)",
  low: "var(--color-accent-green)",
};

const SEVERITY_LABELS: { key: string; cls: string }[] = [
  { key: "critical", cls: "bg-accent-red" },
  { key: "high", cls: "bg-accent-orange" },
  { key: "medium", cls: "bg-accent-purple" },
  { key: "low", cls: "bg-accent-green" },
];

export function PerformanceGraph({ graphData }: PerformanceGraphProps) {
  const nodes: Node[] = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes.map((n) => ({
      id: n.id,
      position: { x: n.position_x, y: n.position_y },
      data: {
        label: (
          <div className="text-xs space-y-1">
            <div className="font-semibold">{n.label}</div>
            <div className="text-[10px] opacity-50">{n.file}</div>
            {n.avg_time_ms != null && (
              <div className="text-[10px]">{n.avg_time_ms.toFixed(1)}ms</div>
            )}
            {n.memory_mb != null && (
              <div className="text-[10px]">{n.memory_mb.toFixed(1)}MB</div>
            )}
          </div>
        ),
      },
      style: {
        background: "var(--color-dark)",
        border: `2px solid ${SEVERITY_COLORS[n.severity || "low"] || "rgba(245,240,232,0.15)"}`,
        borderRadius: "8px",
        padding: "12px",
        color: "var(--color-light)",
        minWidth: "140px",
      },
    }));
  }, [graphData]);

  const edges: Edge[] = useMemo(() => {
    if (!graphData) return [];
    return graphData.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      style: { stroke: "rgba(245, 240, 232, 0.2)" },
      labelStyle: { fill: "rgba(245, 240, 232, 0.5)", fontSize: 10 },
      animated: true,
    }));
  }, [graphData]);

  if (!graphData) {
    return (
      <Card className="bg-light/5">
        <CardHeader>
          <CardTitle className="text-sm text-light/50">
            Performance Graph
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-96 flex items-center justify-center">
            <Skeleton className="w-full h-full rounded-lg" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-light/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-light/50 flex items-center justify-between">
          Performance Graph
          <div className="flex items-center gap-3 text-[10px]">
            {SEVERITY_LABELS.map(({ key, cls }) => (
              <div key={key} className="flex items-center gap-1">
                <div className={`w-2.5 h-2.5 rounded-full ${cls}`} />
                <span className="capitalize">{key}</span>
              </div>
            ))}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[500px] rounded-lg overflow-hidden bg-dark">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="rgba(245, 240, 232, 0.06)" gap={20} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const severity = graphData.nodes.find(
                  (gn) => gn.id === n.id
                )?.severity;
                return SEVERITY_COLORS[severity || "low"] || "rgba(245,240,232,0.15)";
              }}
            />
          </ReactFlow>
        </div>
      </CardContent>
    </Card>
  );
}
