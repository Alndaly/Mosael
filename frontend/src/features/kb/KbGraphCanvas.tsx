import React from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

import type { components } from "@/api/generated/schema";

type GraphNode = components["schemas"]["KbGraphNode"];
type GraphEdge = components["schemas"]["KbGraphEdge"];

interface SimNode extends SimulationNodeDatum {
  id: string;
  label: string;
  kind: string;
  degree: number;
}

const W = 900;
const H = 560;

/**
 * 知识图谱力导向可视化(SVG + d3-force 静态布局)。文档节点 / 实体节点两色,
 * 半径按度数放大;悬停高亮邻居、其余淡出。滚轮缩放、拖拽平移。
 */
export function KbGraphCanvas({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const layout = React.useMemo(() => {
    const simNodes: SimNode[] = nodes.map((node) => ({
      id: node.id,
      label: node.label,
      kind: node.kind,
      degree: 0,
    }));
    const byId = new Map(simNodes.map((node) => [node.id, node]));
    const links: SimulationLinkDatum<SimNode>[] = edges
      .filter((edge) => byId.has(edge.source) && byId.has(edge.target))
      .map((edge) => ({ source: edge.source, target: edge.target }));
    for (const edge of edges) {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (a) a.degree += 1;
      if (b) b.degree += 1;
    }
    const simulation = forceSimulation(simNodes)
      .force("charge", forceManyBody().strength(-180))
      .force(
        "link",
        forceLink<SimNode, SimulationLinkDatum<SimNode>>(links)
          .id((node) => node.id)
          .distance(72),
      )
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide(24))
      .stop();
    for (let i = 0; i < 300; i += 1) simulation.tick();
    // 邻接表:悬停高亮用
    const neighbors = new Map<string, Set<string>>();
    for (const edge of edges) {
      if (!neighbors.has(edge.source)) neighbors.set(edge.source, new Set());
      if (!neighbors.has(edge.target)) neighbors.set(edge.target, new Set());
      neighbors.get(edge.source)!.add(edge.target);
      neighbors.get(edge.target)!.add(edge.source);
    }
    return { simNodes, links, neighbors, byId };
  }, [nodes, edges]);

  const [hover, setHover] = React.useState<string | null>(null);
  // 视图变换:滚轮缩放 + 拖拽平移
  const [view, setView] = React.useState({ k: 1, x: 0, y: 0 });
  const dragRef = React.useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);

  // Wheel-zoom has to be bound by hand with { passive: false }. React attaches wheel listeners
  // passively at the root, so preventDefault() from an onWheel prop is ignored — the graph
  // zoomed AND the KB page scrolled underneath it at the same time.
  React.useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      setView((v) => ({ ...v, k: Math.min(3, Math.max(0.3, v.k * (event.deltaY < 0 ? 1.1 : 0.9))) }));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const isDim = (id: string) =>
    hover !== null && id !== hover && !(layout.neighbors.get(hover)?.has(id) ?? false);

  return (
    <svg
      ref={svgRef}
      className="kb-graph-svg"
      viewBox={`0 0 ${W} ${H}`}
      onPointerDown={(event) => {
        (event.target as Element).setPointerCapture?.(event.pointerId);
        dragRef.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
      }}
      onPointerMove={(event) => {
        if (!dragRef.current) return;
        setView((v) => ({
          ...v,
          x: dragRef.current!.vx + (event.clientX - dragRef.current!.x),
          y: dragRef.current!.vy + (event.clientY - dragRef.current!.y),
        }));
      }}
      onPointerUp={() => {
        dragRef.current = null;
      }}
    >
      <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
        {layout.links.map((link, i) => {
          const s = link.source as SimNode;
          const t = link.target as SimNode;
          const dim = isDim(s.id) && isDim(t.id);
          return (
            <line
              key={i}
              className="kb-graph-edge"
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              opacity={dim ? 0.12 : 0.5}
            />
          );
        })}
        {layout.simNodes.map((node) => {
          const r = (node.kind === "document" ? 9 : 6) + Math.min(node.degree, 8) * 1.1;
          return (
            <g
              key={node.id}
              transform={`translate(${node.x} ${node.y})`}
              className={`kb-graph-node kind-${node.kind}`}
              opacity={isDim(node.id) ? 0.2 : 1}
              onPointerEnter={() => setHover(node.id)}
              onPointerLeave={() => setHover(null)}
            >
              <circle r={r} />
              <text x={r + 3} y={4}>
                {node.label.length > 14 ? `${node.label.slice(0, 14)}…` : node.label}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
