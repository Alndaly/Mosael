import React from "react";
import { cn } from "@/lib/utils";

/** The page owns its title, description and primary action; collections own their filters. */
export function PageHeading({ title, description, count, actions, className }: {
  title: string; description?: string; count?: number; actions?: React.ReactNode; className?: string;
}) {
  return <header data-slot="page-heading" className={cn("flex shrink-0 flex-wrap items-end justify-between gap-x-8 gap-y-4", className)}>
    <div className="min-w-0">
      <div className="flex items-center gap-3"><h2 className="m-0 text-ui-title font-semibold leading-tight tracking-tight">{title}</h2>{count !== undefined && <span className="rounded-md bg-secondary px-2 py-1 text-ui-sm tabular-nums text-muted-foreground">{count}</span>}</div>
      {description && <p className="mb-0 mt-2 max-w-2xl text-ui-sm leading-relaxed text-muted-foreground">{description}</p>}
    </div>
    {actions && <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div>}
  </header>;
}

export const STUDIO_PAGE = "flex h-full min-h-0 flex-col gap-7 overflow-auto px-6 py-7 xl:px-9 xl:py-8 [&>*]:shrink-0";

/** A compact, keyboard-accessible choice strip; selection is explicit even without color. */
export function CollectionTabs<T extends string>({ value, onChange, items, label }: {
  value: T; onChange: (value: T) => void; items: { value: T; label: string; count?: number }[]; label: string;
}) {
  return <div role="group" aria-label={label} className="flex min-w-0 gap-5 overflow-x-auto">
    {items.map(item => <button key={item.value} type="button" aria-label={`${item.label}${item.count !== undefined ? ` ${item.count}` : ""}`} aria-pressed={value === item.value} onClick={() => onChange(item.value)} className={cn("flex h-10 shrink-0 cursor-pointer items-center gap-2 border-b-2 border-transparent px-1 text-ui-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset", value === item.value && "border-primary text-primary")}>
      {item.label}{item.count !== undefined && <span className="text-ui-xs tabular-nums text-muted-foreground">{item.count}</span>}
    </button>)}
  </div>;
}
