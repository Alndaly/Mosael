/** Shared geometry for controls and docked panels layered over a canvas. */
export const CANVAS_TOOLBAR_HEIGHT_PX = 42;
export const CANVAS_PANEL_GAP_PX = 8;
export const CANVAS_PANEL_EDGE_INSET_PX = 8;

/** Keep the panel one standard gap below the floating toolbar. */
export function canvasPanelTop(toolbarTop: number): number {
  return toolbarTop + CANVAS_TOOLBAR_HEIGHT_PX + CANVAS_PANEL_GAP_PX;
}
