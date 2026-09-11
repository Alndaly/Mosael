import React from "react";

import { assetThumbnailUrl } from "@/api/client";

export interface PreviewItem { id: string; x: number; y: number; width?: number; height?: number; label?: string; assetId?: string; }

type Box = PreviewItem & { width: number; height: number };

/**
 * 画布上的一项。带素材的画它的缩略图,没有的画一个占位。
 *
 * **取不到缩略图时要退回占位,而不是把浏览器那张破图摆出来**:节点指着的素材可能还没生成完、
 * 已经被删了,或者这会儿取不到 —— 这三种情况下 SVG `<image>` 会画出一个撕裂的图片图标,
 * 它既不表达"这里是什么",也不表达"出什么事了",只是看着像坏了。退回占位画的是
 * 「一个图片节点,暂时没有画面」,那正是实情。
 *
 * key 里带上 assetId,所以换了素材会重新试一次,不会因为上一张挂过就一直是占位。
 */
function PreviewBox({ item }: { item: Box }) {
  const [broken, setBroken] = React.useState(false);
  const thumbnail = item.assetId && !broken;
  return <g>
    <rect x={item.x} y={item.y} width={item.width} height={item.height} rx="8" fill="var(--panel)" stroke="var(--border-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
    {thumbnail ? <image href={assetThumbnailUrl(item.assetId!)} x={item.x+4} y={item.y+4} width={item.width-8} height={item.height-8} preserveAspectRatio="xMidYMid meet" onError={() => setBroken(true)} /> : <>
      <rect x={item.x+12} y={item.y+14} width={Math.min(24,item.width-24)} height="7" rx="3" fill="var(--primary)" />
      <text x={item.x+12} y={item.y+43} fontSize="14" fill="var(--foreground)">{item.label?.slice(0,18)}</text>
      <rect x={item.x+12} y={item.y+item.height-20} width={Math.max(20,item.width*.55)} height="4" rx="2" fill="var(--border)" />
    </>}
  </g>;
}

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
      {boxes.map(item => <PreviewBox key={`${item.id}:${item.assetId ?? ""}`} item={item} />)}
    </svg>
  </div>;
}
