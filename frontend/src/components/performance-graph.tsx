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
  BaseEdge,
  getBezierPath,
  type Node,
  type Edge,
  type NodeProps,
  type EdgeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { GraphData, GraphNode as GraphNodeData, NodeType, EdgeType } from "@/lib/api";
import { Globe, Brain, Database, Split, SquareFunction, Gauge, Save } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const SEVERITY_COLORS: Record<string, string> = {
  critical: "var(--color-accent-red)",
  high: "var(--color-accent-orange)",
  medium: "var(--color-accent-yellow)",
  low: "var(--color-light)",
};

const SEVERITY_LABELS: { key: string; cls: string }[] = [
  { key: "critical", cls: "bg-accent-red" },
  { key: "high", cls: "bg-accent-orange" },
  { key: "medium", cls: "bg-accent-yellow" },
];

const NODE_TYPE_CONFIG: Record<
  NodeType,
  { icon: React.ReactNode; accent: string; label: string }
> = {
  api: {
    icon: <Globe className="w-4 h-4" />,
    accent: "var(--color-accent-purple)",
    label: "API Request",
  },
  llm: {
    icon: <Brain className="w-4 h-4" />,
    accent: "var(--color-accent-pink)",
    label: "LLM Call",
  },
  db: {
    icon: <Database className="w-4 h-4" />,
    accent: "var(--color-accent-orange)",
    label: "Database",
  },
  condition: {
    icon: <Split className="w-4 h-4" />,
    accent: "var(--color-accent-blue)",
    label: "Condition",
  },
  function: {
    icon: <SquareFunction className="w-4 h-4" />,
    accent: "var(--color-accent-green)",
    label: "Function",
  },
};

const LOOP_BACK_COLOR = "var(--color-accent-blue)";
const DEFAULT_EDGE_COLOR = "var(--color-light)";

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
  const g = new Dagre.graphlib.Graph({ multigraph: true }).setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 100, marginx: 40, marginy: 40 });

  for (const n of graphData.nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: estimateNodeHeight(n) });
  }

  for (let i = 0; i < graphData.edges.length; i++) {
    const e = graphData.edges[i];
    g.setEdge(e.source, e.target, { weight: e.edge_type === "loop_back" ? 0 : 1 }, `e-${i}`);
  }

  Dagre.layout(g);

  // 1. Pre-calculate the bounding boxes for all nodes to detect local collisions
  let graphTopY = Infinity;
  let graphBottomY = -Infinity;
  const nodeBoxes = graphData.nodes.map((n) => {
    const pos = g.node(n.id);
    const h = estimateNodeHeight(n);
    const top = pos.y - h / 2;
    const bottom = pos.y + h / 2;
    
    graphTopY = Math.min(graphTopY, top);
    graphBottomY = Math.max(graphBottomY, bottom);

    return {
      id: n.id,
      left: pos.x - NODE_WIDTH / 2,
      right: pos.x + NODE_WIDTH / 2,
      top,
      bottom,
      centerY: pos.y,
    };
  });

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

  const severityColorOf = (id: string): string => {
    const node = graphData.nodes.find((n) => n.id === id);
    return SEVERITY_COLORS[node?.severity || "low"] ?? DEFAULT_EDGE_COLOR;
  };

  const edges: Edge[] = graphData.edges.map((e, i) => {
    const edgeType: EdgeType = e.edge_type || "call";
    const isLoopBack = edgeType === "loop_back";
    const isBranch = edgeType === "branch_true" || edgeType === "branch_false";

    let sourceHandle: string | undefined;
    let targetHandle: string | undefined;

    if (isLoopBack) {
      const srcBox = nodeBoxes.find((b) => b.id === e.source);
      const tgtBox = nodeBoxes.find((b) => b.id === e.target);

      if (srcBox && tgtBox) {
        // Find the horizontal span that this loopback edge covers
        const spanLeft = Math.min(srcBox.left, tgtBox.left);
        const spanRight = Math.max(srcBox.right, tgtBox.right);
        const avgY = (srcBox.centerY + tgtBox.centerY) / 2;

        let closestTopDist = Infinity;
        let closestBottomDist = Infinity;

        // 2. Check all other nodes to see if they are acting as obstacles
        for (const box of nodeBoxes) {
          if (box.id === e.source || box.id === e.target) continue;

          // If the node sits horizontally between our source and target
          if (box.left <= spanRight && box.right >= spanLeft) {
            if (box.centerY < avgY) {
              // Obstacle is above our nodes
              const dist = avgY - box.bottom;
              if (dist < closestTopDist) closestTopDist = dist;
            } else {
              // Obstacle is below our nodes
              const dist = box.top - avgY;
              if (dist < closestBottomDist) closestBottomDist = dist;
            }
          }
        }

        // 3. Choose the side with the most local clearance
        if (closestTopDist === Infinity && closestBottomDist === Infinity) {
          // Fallback: If no obstacles exist locally, use global graph bounds
          const topClearance = avgY - graphTopY;
          const bottomClearance = graphBottomY - avgY;
          const side = topClearance >= bottomClearance ? "loop_top" : "loop_bottom";
          sourceHandle = side;
          targetHandle = side;
        } else {
          // Primary heuristic: Go the direction with the furthest obstacle
          const side = closestTopDist >= closestBottomDist ? "loop_top" : "loop_bottom";
          sourceHandle = side;
          targetHandle = side;
        }
      }
    } else if (isBranch) {
      const srcBox = nodeBoxes.find((b) => b.id === e.source);
      const tgtBox = nodeBoxes.find((b) => b.id === e.target);
      const srcY = srcBox?.centerY ?? 0;
      const tgtY = tgtBox?.centerY ?? 0;
      sourceHandle = tgtY <= srcY ? "branch_top" : "branch_bottom";
    }

    const sourceColor = isLoopBack ? LOOP_BACK_COLOR : severityColorOf(e.source);
    const targetColor = isLoopBack ? LOOP_BACK_COLOR : severityColorOf(e.target);

    return {
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      sourceHandle,
      targetHandle,
      label: e.label || undefined,
      type: "gradient",
      animated: isLoopBack,
      style: {
        strokeWidth: isLoopBack ? 2 : 1.5,
        strokeDasharray: isLoopBack ? "6 3" : undefined,
      },
      data: { sourceColor, targetColor },
      labelStyle: { fill: targetColor, fontSize: 10, fontWeight: 500 },
      labelBgStyle: { fill: "var(--color-dark)", fillOpacity: 0.85 },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: targetColor,
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
        <span className="flex items-center gap-0.5 opacity-50"><Gauge className="w-3 h-3" />{node.avg_time_ms.toFixed(1)}ms</span>
      )}
      {node.memory_mb != null && (
        <span className="flex items-center gap-0.5 opacity-50"><Save className="w-3 h-3" />{node.memory_mb.toFixed(1)}MB</span>
      )}
    </div>
  );
}

function NodeShell({
  node,
  selected,
  children,
}: {
  node: GraphNodeData;
  selected?: boolean;
  children?: React.ReactNode;
}) {
  const config = NODE_TYPE_CONFIG[node.node_type] ?? NODE_TYPE_CONFIG.function;
  const severityColor =
    SEVERITY_COLORS[node.severity || "low"] || "rgba(245,240,232,0.15)";

  return (
    <>
      <Handle type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2 !border-0" />
      
      <div
        className="rounded-lg overflow-hidden text-light min-w-[180px] max-w-[240px] transition-all duration-200"
        style={{
          background: "var(--color-dark)",
          border: selected ? `2px solid var(--color-accent-blue)` : `2px solid ${severityColor}`,
          boxShadow: selected ? `0 0 15px var(--color-accent-blue)` : undefined,
        }}
      >
        {/* Accent bar + header */}
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: `1px solid ${config.accent}33` }}
        >
          <div
            className="flex items-center justify-center w-7 h-7 rounded-lg shrink-0 text-white"
            style={{ background: config.accent }}
          >
            {config.icon}
          </div>
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
      <Handle type="source" position={Position.Right} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="source" id="loop_top" position={Position.Top} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="target" id="loop_top" position={Position.Top} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="source" id="loop_bottom" position={Position.Bottom} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="target" id="loop_bottom" position={Position.Bottom} className="!opacity-0 !w-2 !h-2 !border-0" />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Custom node components                                             */
/* ------------------------------------------------------------------ */

const ApiNode = memo(function ApiNode({ data, selected }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node} selected={selected}>
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
      {(node.inputs || node.outputs) && (
        <div className="px-2 py-1 rounded bg-light/5 font-mono space-y-0.5">
          {node.inputs && <KeyValueRows data={node.inputs} />}
          {node.outputs && <KeyValueRows data={node.outputs} />}
        </div>
      )}
    </NodeShell>
  );
});

const LlmNode = memo(function LlmNode({ data, selected }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node} selected={selected}>
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
      {(node.inputs || node.outputs) && (
        <div className="px-2 py-1 rounded bg-light/5 font-mono space-y-0.5">
          {node.inputs && <KeyValueRows data={node.inputs} />}
          {node.outputs && <KeyValueRows data={node.outputs} />}
        </div>
      )}
    </NodeShell>
  );
});

const DbNode = memo(function DbNode({ data, selected }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node} selected={selected}>
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
      {(node.inputs || node.outputs) && (
        <div className="px-2 py-1 rounded bg-light/5 font-mono space-y-0.5">
          {node.inputs && <KeyValueRows data={node.inputs} />}
          {node.outputs && <KeyValueRows data={node.outputs} />}
        </div>
      )}
    </NodeShell>
  );
});

const ConditionNode = memo(function ConditionNode({ data, selected }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  const config = NODE_TYPE_CONFIG.condition;
  const severityColor = SEVERITY_COLORS[node.severity || "low"] || DEFAULT_EDGE_COLOR;
  
  return (
    <>
      <Handle type="target" position={Position.Left} className="!opacity-0 !w-2 !h-2 !border-0" />
      <div
        className="rounded-lg overflow-hidden text-light min-w-[180px] max-w-[240px] transition-all duration-200"
        style={{
          background: "var(--color-dark)",
          border: selected ? `2px solid var(--color-accent-blue)` : `2px solid ${severityColor}`,
          boxShadow: selected ? `0 0 15px var(--color-accent-blue)` : undefined,
        }}
      >
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ borderBottom: `1px solid ${config.accent}33` }}
        >
          <div
            className="flex items-center justify-center w-7 h-7 rounded-lg shrink-0 text-white"
            style={{ background: config.accent }}
          >
            {config.icon}
          </div>
          <div className="min-w-0">
            <div className="text-[9px] uppercase tracking-wider opacity-40">
              {config.label}
            </div>
            <div className="text-xs font-semibold truncate">{node.label}</div>
          </div>
        </div>
        <div className="px-3 py-2 space-y-1.5">
          <div className="text-[10px] opacity-30 truncate">{node.file}</div>
          {node.metadata?.condition && (
            <div className="text-[10px] px-2 py-1 rounded bg-accent-blue/10 text-accent-blue/80 font-mono">
              {node.metadata.condition}
            </div>
          )}
          <NodeMetrics node={node} />
        </div>
      </div>

      {/* Default forward handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="default"
        className="!opacity-0 !w-2 !h-2 !border-0"
      />
      
      {/* 
        NEW: Changed Position.Top to Position.Right, added top: 30% 
        This is for the branch going UP, so it exits near the top-right corner.
      */}
      <Handle
        type="source"
        position={Position.Right}
        id="branch_top"
        style={{ top: '30%' }}
        className="!opacity-0 !w-2 !h-2 !border-0"
      />
      
      {/* 
        NEW: Changed Position.Bottom to Position.Right, added top: 70% 
        This is for the branch going DOWN, so it exits near the bottom-right corner.
      */}
      <Handle
        type="source"
        position={Position.Right}
        id="branch_bottom"
        style={{ top: '70%' }}
        className="!opacity-0 !w-2 !h-2 !border-0"
      />

      {/* Your existing loop handles */}
      <Handle type="source" id="loop_top" position={Position.Top} style={{ left: '30%' }} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="target" id="loop_top" position={Position.Top} style={{ left: '70%' }} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="source" id="loop_bottom" position={Position.Bottom} style={{ left: '30%' }} className="!opacity-0 !w-2 !h-2 !border-0" />
      <Handle type="target" id="loop_bottom" position={Position.Bottom} style={{ left: '70%' }} className="!opacity-0 !w-2 !h-2 !border-0" />
    </>
  );
});

const FunctionNode = memo(function FunctionNode({ data, selected }: NodeProps) {
  const node = (data as unknown as SemanticNodeData).graphNode;
  return (
    <NodeShell node={node} selected={selected}>
      {node.inputs && (
        <div>
          <div className="text-[9px] uppercase tracking-wider opacity-30 mb-0.5">
            Inputs
          </div>
          <div className="px-2 py-1 rounded bg-light/5 font-mono">
            <KeyValueRows data={node.inputs} />
          </div>
        </div>
      )}
      {node.outputs && (
        <div>
          <div className="text-[9px] uppercase tracking-wider opacity-30 mb-0.5">
            Outputs
          </div>
          <div className="px-2 py-1 rounded bg-light/5 font-mono">
            <KeyValueRows data={node.outputs} />
          </div>
        </div>
      )}
    </NodeShell>
  );
});

/* ------------------------------------------------------------------ */
/*  Custom edge component                                              */
/* ------------------------------------------------------------------ */

function GradientEdge(props: EdgeProps) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    markerEnd,
    data,
  } = props;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const gradientId = `edge-gradient-${id}`;
  const {
    sourceColor = DEFAULT_EDGE_COLOR,
    targetColor = DEFAULT_EDGE_COLOR,
  } = (data as Record<string, string>) ?? {};

  return (
    <>
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1={sourceX}
          y1={sourceY}
          x2={targetX}
          y2={targetY}
        >
          <stop offset="0%" style={{ stopColor: sourceColor }} />
          <stop offset="100%" style={{ stopColor: targetColor }} />
        </linearGradient>
      </defs>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{ ...style, stroke: `url(#${gradientId})` }}
        markerEnd={markerEnd}
        label={props.label}
        labelStyle={props.labelStyle}
        labelBgStyle={props.labelBgStyle}
        labelBgPadding={props.labelBgPadding as [number, number]}
        labelBgBorderRadius={props.labelBgBorderRadius}
        labelX={labelX}
        labelY={labelY}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Type registries                                                    */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  api: ApiNode,
  llm: LlmNode,
  db: DbNode,
  condition: ConditionNode,
  function: FunctionNode,
};

const edgeTypes = {
  gradient: GradientEdge,
};

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

interface PerformanceGraphProps {
  graphData: GraphData | null;
  variant?: "card" | "fullscreen";
  selectedNodeIds?: string[];
  onNodeClick?: (nodeId: string) => void;
}

export function PerformanceGraph({ 
  graphData, 
  variant = "card", 
  selectedNodeIds, 
  onNodeClick 
}: PerformanceGraphProps) {
  const { layoutedNodes, edges } = useMemo<{ layoutedNodes: Node[]; edges: Edge[] }>(() => {
    if (!graphData) return { layoutedNodes: [], edges: [] };
    const res = getLayoutedElements(graphData);
    return { layoutedNodes: res.nodes, edges: res.edges };
  }, [graphData]);

  const nodes = useMemo(() => {
    if (!selectedNodeIds) return layoutedNodes;
    return layoutedNodes.map(n => ({
      ...n,
      selected: selectedNodeIds.includes(n.id)
    }));
  }, [layoutedNodes, selectedNodeIds]);

  if (!graphData) {
    if (variant === "fullscreen") {
      return (
        <div className="w-full h-full relative flex items-center justify-center bg-dark/50">
          <Skeleton className="w-1/2 h-1/2 rounded-lg opacity-20" />
        </div>
      );
    }
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

  const handleNodeClick = useMemo(() => {
    if (!onNodeClick) return undefined;
    return (_: React.MouseEvent, node: Node) => onNodeClick(node.id);
  }, [onNodeClick]);

  const flowProps = {
    nodes,
    edges,
    nodeTypes,
    edgeTypes,
    fitView: true,
    proOptions: { hideAttribution: true },
    onNodeClick: handleNodeClick,
  };

  if (variant === "fullscreen") {
    return (
      <div className="w-full h-full relative">
        <ReactFlow {...flowProps}>
          <Background color="oklch(0.9569 0.0235 75.73 / 0.03)" gap={32} size={1} />
        </ReactFlow>
      </div>
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
          <ReactFlow {...flowProps}>
          </ReactFlow>
        </div>
      </CardContent>
    </Card>
  );
}
