/** Shared geometry for controls and docked panels layered over a canvas. */
export const CANVAS_TOOLBAR_HEIGHT_PX = 42;
export const CANVAS_PANEL_GAP_PX = 8;
export const CANVAS_PANEL_EDGE_INSET_PX = 8;

/** Translucent surface shared by controls and utility windows over a canvas. */
export const CANVAS_GLASS_SURFACE_CLASS =
  "border border-border bg-panel/90 shadow-[var(--shadow-panel)] backdrop-blur-xl " +
  "supports-[backdrop-filter]:bg-panel/80";

/** Keep the panel one standard gap below the floating toolbar. */
export function canvasPanelTop(toolbarTop: number): number {
  return toolbarTop + CANVAS_TOOLBAR_HEIGHT_PX + CANVAS_PANEL_GAP_PX;
}

/**
 * Geometry shared by every docked panel layered over a full-bleed canvas.
 *
 * Keep this as the single source of truth for both the panel and its resize
 * handle.  If callers calculate either edge independently, the visible grip
 * drifts even when the panel itself is aligned.
 */
export function canvasDockedPanelEdges(toolbarTop: number) {
  return {
    top: canvasPanelTop(toolbarTop),
    right: CANVAS_PANEL_EDGE_INSET_PX,
    bottom: CANVAS_PANEL_EDGE_INSET_PX,
  } as const;
}

/** Position a full-height resize handle immediately before a right dock. */
export function canvasRightDockHandleEdges(panelWidth: number, toolbarTop: number) {
  return {
    ...canvasDockedPanelEdges(toolbarTop),
    right: panelWidth + CANVAS_PANEL_EDGE_INSET_PX,
  } as const;
}

/** Width hidden by a right dock, including its outer inset and resize gutter. */
export function canvasRightDockOcclusion(panelWidth: number): number {
  return panelWidth + CANVAS_PANEL_EDGE_INSET_PX + CANVAS_PANEL_GAP_PX;
}
