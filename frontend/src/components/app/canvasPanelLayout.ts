/** Shared geometry for controls and docked panels layered over a canvas. */
export const CANVAS_TOOLBAR_HEIGHT_PX = 42;
export const CANVAS_PANEL_GAP_PX = 8;
export const CANVAS_PANEL_EDGE_INSET_PX = 8;

/**
 * 画布上那层浮起来的东西共用的材质:半透 + 背后模糊 + 一条很轻的描边。
 *
 * **画布内的一切都不投影。** 节点、工具条、生成器面板、评论卡、内嵌选中块都贴着同一张
 * 无限画布;边框和抬高的底色已经说明边界,再给 elevation 就会叠出一圈深色带,缩放后更像
 * 多层。只有遮罩模态和真正浮在画布之外的录制胶囊保留阴影。
 */
export const CANVAS_GLASS_SURFACE_CLASS =
  "canvas-overlay-surface border border-floating-border";

/**
 * 画布上的**浮窗**:合成器、评论卡、智能体面板、执行历史。
 *
 * 收成一处之前,同一张画布上并存着三套:生成合成器用模态表面(半透)、便签/音频/裁剪合成器和
 * 评论卡用 `FLOATING_SURFACE`(**实色 popover**)、面板用画布浮层 —— 三种背景、三种影子。
 * 挨在一起时一眼就看得出不是一套东西。
 *
 * 弹出菜单和气泡不在这里(仍走 FLOATING_SURFACE):它们贴着触发点、说完就走,而浮窗停在画布上,
 * 挡住的每一块都是用户还想看见的东西 —— 这条界线决定了要不要透。
 */
export const CANVAS_WINDOW_SURFACE_CLASS =
  "canvas-overlay-surface rounded-xl border border-floating-border";

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
