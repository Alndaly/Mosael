import React from "react";

import type { WorkflowFileGraph } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * 工作流的节点图缩略预览(ADR 0035):照插件给的图摘要画 —— 节点的位置、大小、种类,连线,分组 —— 不截 ComfyUI 的图。
 * 整张图按比例塞进框里(`meet`),宽的图上下留白、高的图左右留白,不裁。
 *
 * 卡片上只画形状(几十个节点的字缩到卡片大小看不清,只是噪点);详情里大一号,带节点标题和分组名。
 * 颜色按种类:读素材、加载模型、采样、提示词、产出、缺的各一种,注释和别的是淡的;旁路 / 静音的节点画成半透明。
 */

const ROLE_FILL: Record<string, string> = {
  input: "fill-[var(--chart-image)]",
  model: "fill-primary",
  sampler: "fill-[var(--chart-video)]",
  text: "fill-[var(--chart-audio)]",
  output: "fill-success",
  missing: "fill-destructive",
  note: "fill-muted-foreground",
  other: "fill-muted-foreground",
};
const ROLE_OPACITY: Record<string, number> = { note: 0.25, other: 0.45 };
const PADDING = 40;

function bounds(graph: WorkflowFileGraph | undefined): { x: number; y: number; w: number; h: number } | null {
  const boxes = [...(graph?.nodes ?? []), ...(graph?.groups ?? [])];
  if (boxes.length === 0) return null;
  const left = Math.min(...boxes.map((one) => one.x));
  const top = Math.min(...boxes.map((one) => one.y));
  const right = Math.max(...boxes.map((one) => one.x + one.w));
  const bottom = Math.max(...boxes.map((one) => one.y + one.h));
  return { x: left - PADDING, y: top - PADDING, w: Math.max(right - left, 1) + PADDING * 2, h: Math.max(bottom - top, 1) + PADDING * 2 };
}

/** 一根连线:从上游节点右边、离顶一截的地方,弯到下游节点左边。 */
function linkPath(from: { x: number; y: number; w: number; h: number }, to: { x: number; y: number; w: number; h: number }) {
  const startX = from.x + from.w;
  const startY = from.y + Math.min(from.h / 2, 40);
  const endX = to.x;
  const endY = to.y + Math.min(to.h / 2, 40);
  const bend = Math.max(Math.abs(endX - startX) / 2, 40);
  return `M${startX},${startY} C${startX + bend},${startY} ${endX - bend},${endY} ${endX},${endY}`;
}

const shortTitle = (title: string) => (title.length > 28 ? `${title.slice(0, 27)}…` : title);

export function WorkflowGraphView({
  graph,
  detailed = false,
  label,
  className,
}: {
  graph: WorkflowFileGraph | undefined;
  /** 详情里那一张:带节点标题和分组名。 */
  detailed?: boolean;
  /** 读屏念的(「人像的节点图」)。 */
  label: string;
  className?: string;
}) {
  const box = bounds(graph);
  const nodes = graph?.nodes ?? [];
  return (
    <svg
      data-workflow-graph=""
      role="img"
      aria-label={label}
      viewBox={box ? `${box.x} ${box.y} ${box.w} ${box.h}` : "0 0 100 100"}
      preserveAspectRatio="xMidYMid meet"
      className={cn("block bg-panel-inset", className)}
    >
      {(graph?.groups ?? []).map((group, index) => (
        <g key={`g${index}`}>
          <rect
            x={group.x}
            y={group.y}
            width={group.w}
            height={group.h}
            rx={12}
            className={group.color ? undefined : "fill-muted-foreground"}
            style={group.color ? { fill: group.color } : undefined}
            opacity={0.14}
          />
          {detailed && group.title && (
            // 字号是图里的坐标单位(跟着整张图一起缩放),不是界面字号
            <text x={group.x + 14} y={group.y + 30} fontSize={22} className="fill-muted-foreground font-semibold">
              {shortTitle(group.title)}
            </text>
          )}
        </g>
      ))}
      {(graph?.links ?? []).map(([from, to], index) =>
        nodes[from] && nodes[to] ? (
          <path
            key={`l${index}`}
            data-graph-link=""
            d={linkPath(nodes[from], nodes[to])}
            fill="none"
            className="stroke-muted-foreground"
            strokeWidth={detailed ? 1.5 : 1}
            strokeOpacity={0.55}
            vectorEffect="non-scaling-stroke"
          />
        ) : null,
      )}
      {nodes.map((node, index) => (
        <g key={`n${index}`} data-graph-node="" data-role={node.role} data-muted={node.muted ? "" : undefined} opacity={node.muted ? 0.35 : 1}>
          <rect
            x={node.x}
            y={node.y}
            width={node.w}
            height={node.h}
            rx={10}
            className={ROLE_FILL[node.role] ?? ROLE_FILL.other}
            fillOpacity={ROLE_OPACITY[node.role] ?? 0.75}
          />
          {detailed && node.title && (
            <text x={node.x + 12} y={node.y + 28} fontSize={20} className="fill-foreground font-medium">
              {shortTitle(node.title)}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
