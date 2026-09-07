import { LoadingState } from "./LoadingState";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Restore a saved canvas in place: the loading surface has the same full-bleed
 * bounds and toolbar inset as the editor, without flashing a framed list page. */
export function CanvasDetailLoading({ testId }: { testId: string }) {
  return (
    <div
      className="relative h-full min-h-0 w-full overflow-hidden bg-background"
      data-testid={testId}
      aria-busy="true"
    >
      <LoadingState />
      <div
        className={cn("absolute left-2 top-2 flex h-[42px] items-center gap-2 rounded-lg p-1 pr-3", CANVAS_GLASS_SURFACE_CLASS)}
        aria-hidden="true"
      >
        <Skeleton className="size-8 shrink-0" />
        <Skeleton className="h-3.5 w-28" />
      </div>
    </div>
  );
}
