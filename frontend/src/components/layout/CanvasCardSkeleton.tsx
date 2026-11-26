import { GRID_CARD, GRID_CARD_BODY, GRID_CARD_MEDIA } from "@/components/ui/grid-card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Match the saved canvas preview, title and metadata before collection data arrives. */
export function CanvasCardSkeleton({ description = false }: { description?: boolean }) {
  return (
    <div className={cn(GRID_CARD, "h-full")} aria-hidden="true">
      <Skeleton className={cn(GRID_CARD_MEDIA, "aspect-[16/9] rounded-none")} />
      <div className={GRID_CARD_BODY}>
        <Skeleton className="h-5 w-3/5" />
        {description && (
          <div className="grid gap-2">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-4/5" />
          </div>
        )}
        <Skeleton className="mt-auto h-4 w-2/5" />
      </div>
    </div>
  );
}
