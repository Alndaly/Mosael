"use client";

import { useEffect, useRef, useState } from "react";
import { Dialog } from "radix-ui";
import { BookOpen, List, X } from "lucide-react";
import { DocsLinks, type SidebarGroup } from "./docs-sidebar";
import type { TocEntry } from "@/lib/toc";

export function DocsMobileNav({ groups, entries, labels }: {
  groups: SidebarGroup[];
  entries: TocEntry[];
  labels: { allDocs: string; onThisPage: string; searchClose: string };
}) {
  const [panel, setPanel] = useState<"docs" | "page" | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const desktop = matchMedia("(min-width: 1280px)");
    const closeOnDesktop = () => { if (desktop.matches) setPanel(null); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
  return <>
    <div className="sticky top-20 z-20 -mx-5 flex items-center divide-x divide-border border-b border-border bg-background/95 px-5 backdrop-blur sm:-mx-8 sm:px-8 lg:col-start-2 xl:hidden">
      {(["docs", "page"] as const).map((mode) => {
        if (mode === "page" && !entries.length) return null;
        const Icon = mode === "docs" ? BookOpen : List;
        return <button key={mode} type="button" aria-haspopup="dialog" aria-expanded={panel === mode}
          className={`flex min-h-11 flex-1 items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground ${mode === "docs" ? "lg:hidden" : ""}`}
          onClick={(event) => { trigger.current = event.currentTarget; setPanel(mode); }}>
          <Icon className="size-4" />{mode === "docs" ? labels.allDocs : labels.onThisPage}
        </button>;
      })}
    </div>
    <Dialog.Root open={panel !== null} onOpenChange={(open) => { if (!open) setPanel(null); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/25 backdrop-blur-sm" />
        <Dialog.Content aria-describedby={undefined}
          onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus({ preventScroll: true }); }}
          className="fixed inset-x-3 top-24 bottom-4 z-50 mx-auto flex max-w-lg flex-col overflow-hidden rounded-2xl border border-border/60 bg-background shadow-xl outline-none sm:inset-x-6">
          <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-3">
            <Dialog.Title className="m-0 text-base font-semibold">{panel === "docs" ? labels.allDocs : labels.onThisPage}</Dialog.Title>
            <Dialog.Close aria-label={labels.searchClose} className="grid size-9 place-items-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"><X className="size-4" /></Dialog.Close>
          </div>
          <nav aria-label={panel === "docs" ? labels.allDocs : labels.onThisPage} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
            {panel === "docs" ? <DocsLinks groups={groups} onNavigate={() => setPanel(null)} /> :
              <ul className="m-0 list-none space-y-1 p-0">{entries.map((entry) => <li key={entry.id}>
                <a href={`#${entry.id}`} onClick={() => setPanel(null)}
                  className={`block rounded-md py-2.5 pr-3 text-sm leading-5 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring ${entry.depth === 3 ? "pl-6 text-muted-foreground" : "pl-2 font-medium"}`}>
                  {entry.text}
                </a>
              </li>)}</ul>}
          </nav>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </>;
}
