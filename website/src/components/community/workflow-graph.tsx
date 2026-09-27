import { Code2 } from "lucide-react";

import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from "@/lib/community/workflow-graph";
import type { WorkflowGraph } from "@/lib/community/types";
import { cn } from "@/lib/utils";

/**
 * 工作流的节点图,只读。详情页(服务端)和提交页的预览(浏览器)共用。
 *
 * 不用 React Flow:这里不拖、不连、不缩放,一张 SVG 就够,还不进 JS 包。节点照工作流文件里
 * 应用存下的坐标摆(见 lib/community/workflow-graph)。图比版心宽时横向滚动,不缩到看不清字。
 */
export function WorkflowGraphView({ graph, label, codeLabel, scale = 0.8 }: { graph: WorkflowGraph; label: string; codeLabel: string; scale?: number }) {
  const layout = layoutGraph(graph);
  const pad = 16;
  const width = layout.width + pad * 2;
  const height = layout.height + pad * 2;
  return (
    <div className="overflow-auto rounded-2xl border border-border bg-[radial-gradient(circle,var(--rule)_1px,transparent_1px)] bg-[length:18px_18px] bg-card">
      <svg
        viewBox={`${-pad} ${-pad} ${width} ${height}`}
        width={Math.round(width * scale)}
        height={Math.round(height * scale)}
        aria-label={label}
        className="block max-w-none"
      >
        <defs>
          <marker id="wf-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" className="fill-muted-foreground/60" />
          </marker>
        </defs>
        {layout.edges.map((edge) => (
          <path key={edge.id} d={edge.path} className="fill-none stroke-muted-foreground/45" strokeWidth={1.5} markerEnd="url(#wf-arrow)" />
        ))}
        {layout.nodes.map((node) => (
          <foreignObject key={node.id} x={node.x} y={node.y} width={NODE_WIDTH} height={NODE_HEIGHT}>
            <div
              className={cn(
                "flex h-full flex-col justify-center gap-0.5 rounded-xl border bg-card px-3 shadow-[0_1px_0_var(--border)]",
                node.code ? "border-[color:var(--tile-4)] bg-[color-mix(in_oklab,var(--tile-4)_10%,var(--card))]" : "border-border",
              )}
            >
              <span className="flex min-w-0 items-center gap-1.5 text-[13px] leading-4 font-semibold text-foreground">
                {node.code && <Code2 className="size-3.5 shrink-0 text-[color:var(--tile-4)]" aria-label={codeLabel} />}
                <span className="truncate">{node.name || node.id}</span>
              </span>
              <span className="truncate font-mono text-[11px] leading-4 text-muted-foreground">{node.type}</span>
            </div>
          </foreignObject>
        ))}
      </svg>
    </div>
  );
}
