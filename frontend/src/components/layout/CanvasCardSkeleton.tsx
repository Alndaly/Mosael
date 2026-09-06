import { Skeleton } from "@/components/ui/skeleton";

/** Match the saved canvas preview, title and metadata before collection data arrives. */
export function CanvasCardSkeleton({ description = false }: { description?: boolean }) {
  return (
    <div className="flex h-full min-w-0 flex-col gap-3" aria-hidden="true">
      <Skeleton className="aspect-[16/9] w-full rounded-lg" />
      <Skeleton className="h-5 w-3/5" />
      {description && (
        <div className="grid gap-2 py-1">
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-4/5" />
        </div>
      )}
      <Skeleton className="mt-auto h-4 w-2/5" />
    </div>
  );
}
