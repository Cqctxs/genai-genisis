"use client";

import { memo, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { GraphData, GraphNode as GraphNodeData, NodeType, EdgeType } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

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

const NODE_TYPE_CONFIG: Record<
  NodeType,
  { icon: string; accent: string; label: string }
> = {
  api: {
    icon: "🌐",
    accent: "var(--color-accent-blue)",
    label: "API Request",
  },
  llm: {
    icon: "🧠",
    accent: "var(--color-accent-purple)",
    label: "LLM Call",
  },
  db: {
    icon: "🗄️",
    accent: "var(--color-accent-orange)",
    label: "Database",
  },
  condition: {
    icon: "🔀",
    accent: "var(--color-accent-red)",
    label: "Condition",
  },
  function: {
    icon: "ƒ",
    accent: "var(--color-accent-green)",
    label: "Function",
  },
};

const EDGE_TYPE_COLORS: Record<string, string> = {
  call: "rgba(245, 240, 232, 0.25)",
  branch_true: "var(--color-accent-green)",
  branch_false: "var(--color-accent-red)",
  loop_back: "var(--color-accent-blue)",
};

/* ------------------------------------------------------------------ */
/*  Dagre auto-layout                                                  */
/* ------------------------------------------------------------------ */

const NODE_WIDTH = 240;
const BASE_NODE_HEIGHT = 100;
const KV_ROW_HEIGHT = 14;

function estimateNodeHeight(node: GraphNodeData): number {
  let h = BASE_NODE_HEIGHT;
  const inputCount = node.inputs ? Object.keys(node.inputs).length : 0;
  const outputCount = node.outputs ? Object.keys(node.outputs).length : 0;
  h += (inputCount + outputCount) * KV_ROW_HEIGHT;
  if (node.metadata && Object.keys(node.metadata).length > 0) h += 20;
  if (node.avg_time_ms != null || node.memory_mb != null) h += 18;
  return h;
}

function getLayoutedElements(
  graphData: GraphData,
): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 100, marginx: 40, marginy: 40 });

  for (const n of graphData.nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: estimateNodeHeight(n) });
  }

  for (const e of graphData.edges) {
    if (e.edge_type !== "loop_back") {
      g.setEdge(e.source, e.target);
    }
  }

  Dagre.layout(g);

  const centerY = new Map<string, number>();
  for (const n of graphData.nodes) {
    centerY.set(n.id, g.node(n.id).y);
  }

  const nodes: Node[] = graphData.nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: n.node_type || "function",
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - estimateNodeHeight(n) / 2,
      },
      data: { graphNode: n },
    };
  });

  const edges: Edge[] = graphData.edges.map((e, i) => {
    const edgeType: EdgeType = e.edge_type || "call";
    const isLoopBack = edgeType === "loop_back";
    const isBranch = edgeType === "branch_true" || edgeType === "branch_false";
    const strokeColor = EDGE_TYPE_COLORS[edgeType] || EDGE_TYPE_COLORS.call;

    let sourceHandle: string | undefined;
    let targetHandle: string | undefined;

    if (isLoopBack) {
      sourceHandle = "loop_source";
      targetHandle = "loop_target";
    } else if (isBranch) {
      const srcY = centerY.get(e.source) ?? 0;
      const tgtY = centerY.get(e.target) ?? 0;
      sourceHandle = tgtY <= srcY ? "branch_top" : "branch_bottom";
    }

    return {
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      sourceHandle,
      targetHandle,
      label: e.label || undefined,
      type: "bezier",
      animated: isLoopBack,
      style: {
        stroke: strokeColor,
        strokeWidth: isLoopBack ? 2 : 1.5,
        strokeDasharray: isLoopBack ? "6 3" : undefined,
      },
      labelStyle: {
        fill: strokeColor,
        fontSize: 10,
        fontWeight: 500,
      },
      labelBgStyle: {
        fill: "var(--color-dark)",
        fillOpacity: 0.85,
      },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: strokeColor,
        width: 16,
        height: 16,
      },
    };
  });

  return { nodes, edges };
}

/* ------------------------------------------------------------------ */
/*  Shared node internals                                              */
/* ------------------------------------------------------------------ */

interface SemanticNodeData extends Record<string, unknown> {
  graphNode: GraphNodeData;
}

function KeyValueRows({ data }: { data: Record<string, string> }) {
  return (
    <div className="space-y-0.5">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-1.5 text-[10px]">
          <span className="opacity-40 shrink-0">{k}</span>
          <span className="opacity-70 truncate">{v}</span>
        </div>
      ))}
    </div>
  );
}

function NodeMetrics({ node }: { node: GraphNodeData }) {
  if (node.avg_time_ms == null && node.memory_mb == null) return null;
  return (
    <div className="flex items-center gap-2 text-[10px] pt-1 border-t border-white/5">
      {node.avg_time_ms != null && (
        <span className="opacity-50">⏱ {node.avg_time_ms.toFixed(1)}ms</span>
      )}
      {node.memory_mb != null && (
        <span className="opacity-50">💾 {node.memory_mb.toFixed(1)}MB</span>
      )}
    </div>
  );
}

function NodeShell({
  node,
  children,
}: {
  node: GraphNodeData;
  children?: React.ReactNode;
}) {
  const config = NODE_TYPE_CONFIG[node.node_type] ?? NODE_TYPE_CONFIG.function;
  const severityColor =
    SEVERITY_COLORS[node.severity || "low"] || "rgba(245,240,232,0.15)";

  return (
    <>
      <Handle type="target" position={Position.Left} className="!bg-light/30 !w-2 !h-2 !border-0" />
      <Handle type="target" position={Position.Top} id="loop_target" className="!bg-accent-blue/50 !w-1.5 !h-1.5 !border-0" />
      <div
        className="rounded-lg overflow-hidden text-light min-w-[180px] max-w-[240px]"
        style={{
          background: "var(--color-dark)",
          border: `2px solid ${severityColor}`,
        }}
      >
        {/* Accent bar + header */}
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: `1px solid ${config.accent}33` }}
        >
          <span className="text-sm">{config.icon}</span>
          <div className="min-w-0">
            <div className="text-[9px] uppercase tracking-wider opacity-40">
              {config.label}
            </div>
            <div className="text-xs font-semibold truncate">{node.label}</div>
          </div>
        </div>

        {/* Body */}
        <div className="px-3 py-2 space-y-1.5">
          <div className="text-[10px] opacity-30 truncate">{node.file}</div>
          {children}
          <NodeMetrics node={node} />
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-light/30 !w-2 !h-2 !border-0" />
      <Handle type="source" position={Position.Top} id="loop_source" className="!bg-accent-blue/50 !w-1.5 !h-1.5 !border-0" style={{ left: "75%" }} />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Custom node components                                             */
/* ------------------------------------------------------------------ */

const ApiNode = memo(function ApiNode({ data }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node}>
      {node.metadata && (
        <div className="flex items-center gap-1.5 text-[10px]">
          {node.metadata.method && (
            <span className="px-1.5 py-0.5 rounded bg-accent-blue/20 text-accent-blue font-mono font-semibold">
              {node.metadata.method}
            </span>
          )}
          {node.metadata.endpoint && (
            <span className="opacity-60 truncate font-mono">
              {node.metadata.endpoint}
            </span>
          )}
        </div>
      )}
      {node.inputs && <KeyValueRows data={node.inputs} />}
      {node.outputs && <KeyValueRows data={node.outputs} />}
    </NodeShell>
  );
});

const LlmNode = memo(function LlmNode({ data }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node}>
      {node.metadata && (
        <div className="space-y-0.5 text-[10px]">
          {node.metadata.model && (
            <div className="flex items-center gap-1.5">
              <span className="opacity-40">model</span>
              <span className="opacity-70 font-mono truncate">
                {node.metadata.model}
              </span>
            </div>
          )}
          {node.metadata.purpose && (
            <div className="opacity-50 italic">{node.metadata.purpose}</div>
          )}
        </div>
      )}
      {node.inputs && <KeyValueRows data={node.inputs} />}
      {node.outputs && <KeyValueRows data={node.outputs} />}
    </NodeShell>
  );
});

const DbNode = memo(function DbNode({ data }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node}>
      {node.metadata && (
        <div className="flex items-center gap-1.5 text-[10px]">
          {node.metadata.operation && (
            <span className="px-1.5 py-0.5 rounded bg-accent-orange/20 text-accent-orange font-mono font-semibold">
              {node.metadata.operation}
            </span>
          )}
          {node.metadata.table && (
            <span className="opacity-60 font-mono truncate">
              {node.metadata.table}
            </span>
          )}
        </div>
      )}
      {node.inputs && <KeyValueRows data={node.inputs} />}
      {node.outputs && <KeyValueRows data={node.outputs} />}
    </NodeShell>
  );
});

const ConditionNode = memo(function ConditionNode({ data }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <>
      <Handle type="target" position={Position.Left} className="!bg-light/30 !w-2 !h-2 !border-0" />
      <Handle type="target" position={Position.Top} id="loop_target" className="!bg-accent-blue/50 !w-1.5 !h-1.5 !border-0" style={{ left: "25%" }} />
      <div
        className="rounded-lg overflow-hidden text-light min-w-[180px] max-w-[240px]"
        style={{
          background: "var(--color-dark)",
          border: `2px solid ${SEVERITY_COLORS[node.severity || "low"] || "rgba(245,240,232,0.15)"}`,
          borderLeft: `4px solid var(--color-accent-red)`,
        }}
      >
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: "1px solid rgba(245,240,232,0.06)" }}
        >
          <span className="text-sm">🔀</span>
          <div className="min-w-0">
            <div className="text-[9px] uppercase tracking-wider opacity-40">
              Condition
            </div>
            <div className="text-xs font-semibold truncate">{node.label}</div>
          </div>
        </div>
        <div className="px-3 py-2 space-y-1.5">
          <div className="text-[10px] opacity-30 truncate">{node.file}</div>
          {node.metadata?.condition && (
            <div className="text-[10px] px-2 py-1 rounded bg-accent-red/10 text-accent-red/80 font-mono">
              {node.metadata.condition}
            </div>
          )}
          <NodeMetrics node={node} />
        </div>
      </div>
      {/* Branch handles: position-based — layout picks top/bottom dynamically */}
      <Handle
        type="source"
        position={Position.Right}
        id="default"
        className="!bg-light/30 !w-2 !h-2 !border-0"
      />
      <Handle
        type="source"
        position={Position.Top}
        id="branch_top"
        className="!bg-light/30 !w-2 !h-2 !border-0"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="branch_bottom"
        className="!bg-light/30 !w-2 !h-2 !border-0"
      />
      <Handle
        type="source"
        position={Position.Top}
        id="loop_source"
        className="!bg-accent-blue/50 !w-1.5 !h-1.5 !border-0"
        style={{ left: "80%" }}
      />
    </>
  );
});

const FunctionNode = memo(function FunctionNode({ data }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node}>
      {node.inputs && (
        <div>
          <div className="text-[9px] uppercase tracking-wider opacity-30 mb-0.5">
            Inputs
          </div>
          <KeyValueRows data={node.inputs} />
        </div>
      )}
      {node.outputs && (
        <div>
          <div className="text-[9px] uppercase tracking-wider opacity-30 mb-0.5">
            Outputs
          </div>
          <KeyValueRows data={node.outputs} />
        </div>
      )}
    </NodeShell>
  );
});

/* ------------------------------------------------------------------ */
/*  Node type registry                                                 */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  api: ApiNode,
  llm: LlmNode,
  db: DbNode,
  condition: ConditionNode,
  function: FunctionNode,
};

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

interface PerformanceGraphProps {
  graphData: GraphData | null;
}

export function PerformanceGraph({ graphData }: PerformanceGraphProps) {
  const { nodes, edges } = useMemo<{ nodes: Node[]; edges: Edge[] }>(() => {
    if (!graphData) return { nodes: [], edges: [] };
    return getLayoutedElements(graphData);
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
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="rgba(245, 240, 232, 0.06)" gap={20} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const gn = graphData.nodes.find((gn) => gn.id === n.id);
                const nodeType = gn?.node_type || "function";
                return NODE_TYPE_CONFIG[nodeType]?.accent || "rgba(245,240,232,0.15)";
              }}
            />
          </ReactFlow>
        </div>
      </CardContent>
    </Card>
  );
}
