"use client";

import { useCallback, useMemo } from "react";
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
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#22c55e",
};

export function PerformanceGraph({ graphData }: PerformanceGraphProps) {
  if (!graphData) {
    return (
      <Card className="bg-neutral-900 border-neutral-800">
        <CardHeader>
          <CardTitle className="text-sm text-neutral-400">
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

  const nodes: Node[] = useMemo(
    () =>
      graphData.nodes.map((n) => ({
        id: n.id,
        position: { x: n.position_x, y: n.position_y },
        data: {
          label: (
            <div className="text-xs space-y-1">
              <div className="font-semibold">{n.label}</div>
              <div className="text-[10px] text-neutral-400">{n.file}</div>
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
          background: "#1a1a1a",
          border: `2px solid ${SEVERITY_COLORS[n.severity || "low"] || "#404040"}`,
          borderRadius: "8px",
          padding: "12px",
          color: "#e5e5e5",
          minWidth: "140px",
        },
      })),
    [graphData.nodes]
  );

  const edges: Edge[] = useMemo(
    () =>
      graphData.edges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.label,
        style: { stroke: "#525252" },
        labelStyle: { fill: "#a3a3a3", fontSize: 10 },
        animated: true,
      })),
    [graphData.edges]
  );

  return (
    <Card className="bg-neutral-900 border-neutral-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-neutral-400 flex items-center justify-between">
          Performance Graph
          <div className="flex items-center gap-3 text-[10px]">
            {Object.entries(SEVERITY_COLORS).map(([label, color]) => (
              <div key={label} className="flex items-center gap-1">
                <div
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="capitalize">{label}</span>
              </div>
            ))}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[500px] rounded-lg overflow-hidden bg-neutral-950">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#262626" gap={20} />
            <Controls className="bg-neutral-800 border-neutral-700 rounded" />
            <MiniMap
              className="bg-neutral-900 border-neutral-800 rounded"
              nodeColor={(n) => {
                const severity = graphData.nodes.find(
                  (gn) => gn.id === n.id
                )?.severity;
                return SEVERITY_COLORS[severity || "low"] || "#404040";
              }}
            />
          </ReactFlow>
        </div>
      </CardContent>
    </Card>
  );
}
