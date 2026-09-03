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
