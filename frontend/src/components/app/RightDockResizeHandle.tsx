import { canvasRightDockHandleEdges } from "@/components/app/canvasPanelLayout";
import { SIDEBAR_HANDLE_CLASS, type ResizableSidebar } from "@/lib/useResizableSidebar";
import { cn } from "@/lib/utils";

/**
 * Resize boundary for a panel docked to the right side of a full-bleed canvas.
 *
 * It owns both geometry and drag direction. Callers should not wire a generic
 * left-sidebar handler here: moving this boundary left must make the right dock
 * wider, which is the inverse of a left sidebar.
 */
export function RightDockResizeHandle({
  panel,
  toolbarTop,
  className,
}: {
  panel: Pick<ResizableSidebar, "width" | "startDragFromRight">;
  toolbarTop: number;
  className?: string;
}) {
  return (
    <div
      className={cn(SIDEBAR_HANDLE_CLASS, className)}
      style={canvasRightDockHandleEdges(panel.width, toolbarTop)}
      onPointerDown={panel.startDragFromRight}
      role="separator"
      aria-orientation="vertical"
    />
  );
}
