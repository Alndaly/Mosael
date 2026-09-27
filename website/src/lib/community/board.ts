/**
 * 画板快照(`mosael.board-snapshot/1`)→ 只读画布上的节点与连线。
 *
 * 快照里的格子和桌面应用画布上的同形(ADR 0026 §5「快照格式」),尺寸缺省时用应用的默认尺寸
 * (frontend/src/features/boards/boardNodes.tsx 的 DEFAULT_SIZE),分享出去的画板和本机上的
 * 一样大。媒体只有哈希,地址来自 `GET /shares/{slug}` 回包里的 `media`(哈希 → `{url, content_type}`)。
 *
 * 纯函数,不 import React Flow:测试在 node 里跑,页面拿到的对象正好是 React Flow 要的形状。
 */
import type { BoardSnapshot, ShareDetail, ShareMedia, SnapshotItem, SnapshotMedia } from "@/lib/community/types";

export const SNAPSHOT_SCHEMA = "mosael.board-snapshot/1";

export const DEFAULT_SIZE: Record<string, { width: number; height: number }> = {
  note: { width: 220, height: 140 },
  image: { width: 260, height: 180 },
  video: { width: 320, height: 200 },
  audio: { width: 280, height: 72 },
  frame: { width: 420, height: 300 },
  scene: { width: 320, height: 220 },
  document: { width: 320, height: 300 },
};

const KNOWN = new Set(Object.keys(DEFAULT_SIZE));

/** 便签的六种颜色(和应用同一组)。别的值按黄色画。 */
export const NOTE_COLORS = ["yellow", "blue", "green", "pink", "purple", "gray"] as const;
export type NoteColor = (typeof NOTE_COLORS)[number];

export function noteColor(color: string | undefined): NoteColor {
  return (NOTE_COLORS as readonly string[]).includes(color ?? "") ? (color as NoteColor) : "yellow";
}

/**
 * 媒体地址只收同源路径和 http(s):地址是服务回的,但分享页的 CSP 之外再多一道 —— `javascript:`
 * 或 `data:text/html` 不该有机会进 `<img src>` / `<a href>`。
 */
export function safeMediaUrl(url: string | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/") && !url.startsWith("//")) return url;
  return /^https?:\/\//i.test(url) ? url : null;
}

export type ResolvedMedia = { src: string; thumb: string; width?: number; height?: number; contentType: string };

export function resolveMedia(media: SnapshotMedia | undefined, files: ShareMedia): ResolvedMedia | null {
  if (!media) return null;
  const src = safeMediaUrl(files[media.sha256]?.url);
  if (!src) return null;
  const thumb = (media.thumb_sha256 && safeMediaUrl(files[media.thumb_sha256]?.url)) || src;
  return { src, thumb, width: media.width, height: media.height, contentType: media.content_type };
}

export type BoardNodeData = {
  item: SnapshotItem;
  media: ResolvedMedia | null;
};

export type BoardFlowNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  data: BoardNodeData;
  zIndex: number;
  draggable: false;
  connectable: false;
  selectable: boolean;
};

export type BoardFlowEdge = { id: string; source: string; target: string; label?: string };

export function isSnapshot(value: unknown): value is BoardSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<BoardSnapshot>;
  return snapshot.schema === SNAPSHOT_SCHEMA && Array.isArray(snapshot.items) && Array.isArray(snapshot.edges);
}

/**
 * 分组框垫在最底下(z = -1),其余按快照顺序叠。认不出的格子种类照样画成一个占位格 —— 应用以后
 * 多一种格子,旧的查看页不该整张画板打不开。
 */
export function toFlow(share: Pick<ShareDetail, "snapshot" | "media">): { nodes: BoardFlowNode[]; edges: BoardFlowEdge[] } {
  const items = share.snapshot.items.filter((item) => item && typeof item.id === "string" && Number.isFinite(item.x) && Number.isFinite(item.y));
  const nodes = items.map((item): BoardFlowNode => {
    const kind = KNOWN.has(item.kind) ? item.kind : "unknown";
    const size = DEFAULT_SIZE[kind] ?? { width: 220, height: 140 };
    const media = resolveMedia(kind === "scene" ? (item.preview ?? item.media) : item.media, share.media ?? {});
    return {
      id: item.id,
      type: kind,
      position: { x: item.x, y: item.y },
      width: item.width && item.width > 0 ? item.width : size.width,
      height: item.height && item.height > 0 ? item.height : size.height,
      data: { item, media },
      zIndex: kind === "frame" ? -1 : 0,
      draggable: false,
      connectable: false,
      selectable: kind === "image" || kind === "document",
    };
  });
  const ids = new Set(nodes.map((node) => node.id));
  const edges = share.snapshot.edges
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, ...(edge.label ? { label: edge.label } : {}) }));
  return { nodes, edges };
}
