import React from "react";
import { COMPACT_SIDEBAR_BOUNDS, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";
import { cn } from "@/lib/utils";

export const DETAIL_INDEX_ITEM = "flex min-w-0 cursor-pointer items-center gap-3 rounded-md border-0 bg-transparent px-3 py-3 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring max-[880px]:shrink-0 max-[880px]:py-2";
export const DETAIL_INDEX_SELECTED = "bg-accent text-primary hover:bg-accent";
export const DETAIL_INDEX_TEXT = "min-w-0 [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-ui-sm [&_strong]:font-semibold max-[880px]:[&_small]:hidden";

/** Tasks and installed plugins share the same index, work surface and resizing geometry. */
export function CollectionDetail({ storageKey, label, index, selected, children }: {
  storageKey: string; label: string; index: React.ReactNode; selected: boolean; children: React.ReactNode;
}) {
  const sidebar = useResizableSidebar(storageKey, COMPACT_SIDEBAR_BOUNDS);
  return <div data-slot="collection-detail" className="relative grid min-h-0 flex-1 grid-cols-[var(--studio-index-width)_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-panel max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]"
    style={{ "--studio-index-width": `${sidebar.width}px` } as React.CSSProperties}>
    <aside aria-label={label} className="flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-divider max-[880px]:border-r-0 max-[880px]:border-b">
      <div className="grid content-start gap-1 overflow-y-auto p-1.5 max-[880px]:flex max-[880px]:items-center max-[880px]:overflow-x-auto max-[880px]:p-3">{index}</div>
    </aside>
    <div {...sidebar.handleProps} style={{ left: handleOffset(sidebar.width, { gap: 0 }) }} className={cn(sidebar.handleProps.className, "max-[880px]:hidden")} />
    <div data-slot="collection-detail-content" className={cn("@container/settings grid min-h-0 min-w-0 overflow-y-auto px-6 py-6 xl:px-8", selected ? "content-start" : "place-items-center")}>
      {children}
    </div>
  </div>;
}
