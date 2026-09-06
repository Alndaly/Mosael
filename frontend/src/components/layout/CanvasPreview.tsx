import { assetThumbnailUrl } from "@/api/client";

export interface PreviewItem { id: string; x: number; y: number; width?: number; height?: number; label?: string; assetId?: string; }

/** Read-only overview of the saved canvas, using its real positions and connections. */
export function CanvasPreview({ items, edges = [] }: { items: PreviewItem[]; edges?: { source: string; target: string }[] }) {
  const safe = items.filter(item => Number.isFinite(item.x) && Number.isFinite(item.y));
  const boxes = safe.map(item => ({ ...item, width: Math.max(40, item.width || 200), height: Math.max(30, item.height || 110) }));
  const left = Math.min(0, ...boxes.map(item => item.x)) - 40;
  const top = Math.min(0, ...boxes.map(item => item.y)) - 40;
  const right = Math.max(320, ...boxes.map(item => item.x + item.width)) + 40;
  const bottom = Math.max(180, ...boxes.map(item => item.y + item.height)) + 40;
  const byId = new Map(boxes.map(item => [item.id, item]));
  return <div className="grid aspect-[16/9] w-full place-items-center overflow-hidden rounded-lg border border-border bg-panel-subtle p-5">
    <svg className="h-full w-full overflow-hidden" viewBox={`${left} ${top} ${right-left} ${bottom-top}`} aria-hidden="true">
      {edges.map((edge, i) => { const a = byId.get(edge.source), b = byId.get(edge.target); if (!a || !b) return null; const x1=a.x+a.width, y1=a.y+a.height/2, x2=b.x, y2=b.y+b.height/2; return <path key={i} d={`M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`} fill="none" stroke="var(--primary)" strokeOpacity=".45" strokeWidth="2" vectorEffect="non-scaling-stroke" />; })}
      {boxes.map(item => <g key={item.id}>
        <rect x={item.x} y={item.y} width={item.width} height={item.height} rx="8" fill="var(--panel)" stroke="var(--border-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {item.assetId ? <image href={assetThumbnailUrl(item.assetId)} x={item.x+4} y={item.y+4} width={item.width-8} height={item.height-8} preserveAspectRatio="xMidYMid meet" /> : <>
          <rect x={item.x+12} y={item.y+14} width={Math.min(24,item.width-24)} height="7" rx="3" fill="var(--primary)" />
          <text x={item.x+12} y={item.y+43} fontSize="14" fill="var(--foreground)">{item.label?.slice(0,18)}</text>
          <rect x={item.x+12} y={item.y+item.height-20} width={Math.max(20,item.width*.55)} height="4" rx="2" fill="var(--border)" />
        </>}
      </g>)}
    </svg>
  </div>;
}
