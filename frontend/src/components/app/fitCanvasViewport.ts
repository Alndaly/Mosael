import { getViewportForBounds, type Edge, type Node, type ReactFlowInstance } from "@xyflow/react";

export interface CanvasViewportInsets {
  top?: number;
  right?: number;
  bottom?: number;
  left?: number;
}

export function visibleCanvasSize(
  width: number,
  height: number,
  insets: CanvasViewportInsets,
) {
  const left = Math.max(0, insets.left ?? 0);
  const right = Math.max(0, insets.right ?? 0);
  const top = Math.max(0, insets.top ?? 0);
  const bottom = Math.max(0, insets.bottom ?? 0);
  return {
    left,
    top,
    width: Math.max(1, width - left - right),
    height: Math.max(1, height - top - bottom),
  };
}

/**
 * Fit every node into the part of a React Flow surface that is actually visible.
 *
 * Docked panels are layered over the canvas, so React Flow's built-in fitView
 * measures a larger viewport than the user can see.  Computing the transform
 * against the unobscured rectangle keeps the right-most nodes out from under a
 * dock without changing the canvas or panel layout.
 */
export function fitCanvasViewport<NodeType extends Node = Node, EdgeType extends Edge = Edge>(
  instance: ReactFlowInstance<NodeType, EdgeType>,
  surface: HTMLElement,
  insets: CanvasViewportInsets = {},
  options: { padding?: number; duration?: number; minZoom?: number; maxZoom?: number } = {},
) {
  const nodes = instance.getNodes();
  if (nodes.length === 0) return Promise.resolve(false);

  const visible = visibleCanvasSize(surface.clientWidth, surface.clientHeight, insets);
  const viewport = getViewportForBounds(
    instance.getNodesBounds(nodes),
    visible.width,
    visible.height,
    options.minZoom ?? 0.1,
    options.maxZoom ?? 1,
    options.padding ?? 0.3,
  );
  return instance.setViewport(
    { ...viewport, x: viewport.x + visible.left, y: viewport.y + visible.top },
    { duration: options.duration ?? 250 },
  );
}

/** Center a flow-space point in the unobscured surface, at the requested zoom. */
export function centerCanvasViewport<NodeType extends Node = Node, EdgeType extends Edge = Edge>(
  instance: ReactFlowInstance<NodeType, EdgeType>,
  surface: HTMLElement,
  point: { x: number; y: number },
  insets: CanvasViewportInsets = {},
  options: { zoom?: number; duration?: number } = {},
) {
  const visible = visibleCanvasSize(surface.clientWidth, surface.clientHeight, insets);
  const zoom = options.zoom ?? instance.getZoom();
  return instance.setViewport({
    x: visible.left + visible.width / 2 - point.x * zoom,
    y: visible.top + visible.height / 2 - point.y * zoom,
    zoom,
  }, { duration: options.duration ?? 350 });
}

/**
 * 一张画布上「真正看得见的那块」。
 *
 * 右栏面板(智能体、执行历史)是**盖在画布上**的,不占版面 —— React Flow 量到的永远是整块
 * 画布,照它居中的话,目标正好落在面板底下(用户报过:点「在画布中查看」,评论跳到了智能体
 * 那一栏后面)。停靠的按宽度让开,悬浮的按它此刻的矩形挖掉。
 *
 * 两张画布(创意画板、工作流)的遮挡关系是同一套,所以算法只此一份 —— 各自算一遍的结果是
 * 其中一边先被修好,另一边继续把评论跳到面板底下。
 */
export function canvasInsets(
  surface: HTMLElement | null,
  dockedRight: number,
  floating: Array<Element | null | undefined> = [],
): CanvasViewportInsets {
  let insets: CanvasViewportInsets = { right: dockedRight };
  if (!surface) return insets;
  const bounds = surface.getBoundingClientRect();
  for (const element of floating) {
    if (!element) continue;
    const panel = element.getBoundingClientRect();
    insets = excludeCanvasOverlay(surface.clientWidth, surface.clientHeight, insets, {
      left: panel.left - bounds.left,
      top: panel.top - bounds.top,
      right: panel.right - bounds.left,
      bottom: panel.bottom - bounds.top,
    });
  }
  return insets;
}

/** Keep the largest clear rectangle around a floating panel (coordinates relative to the surface). */
export function excludeCanvasOverlay(
  width: number,
  height: number,
  insets: CanvasViewportInsets,
  overlay: { left: number; top: number; right: number; bottom: number },
): CanvasViewportInsets {
  const visible = visibleCanvasSize(width, height, insets);
  const right = visible.left + visible.width;
  const bottom = visible.top + visible.height;
  if (overlay.right <= visible.left || overlay.left >= right || overlay.bottom <= visible.top || overlay.top >= bottom) return insets;
  const candidates = [
    { ...visible, width: Math.max(0, overlay.left - 8 - visible.left) },
    { ...visible, left: overlay.right + 8, width: Math.max(0, right - overlay.right - 8) },
    { ...visible, height: Math.max(0, overlay.top - 8 - visible.top) },
    { ...visible, top: overlay.bottom + 8, height: Math.max(0, bottom - overlay.bottom - 8) },
  ];
  const clear = candidates.reduce((best, rect) => rect.width * rect.height > best.width * best.height ? rect : best);
  if (clear.width <= 0 || clear.height <= 0) return insets;
  return { left: clear.left, top: clear.top, right: width - clear.left - clear.width, bottom: height - clear.top - clear.height };
}
