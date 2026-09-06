import type { ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/** The same working index stays reachable when the canvas needs the full width. */
export function StudioIndex({ label, children }: { label: string; children: ReactNode }) {
  const narrow = useMediaMatch("(max-width: 820px)");
  if (narrow) {
    return (
      <div className="absolute left-3 top-3 z-30">
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="icon-sm" aria-label={label}><PanelLeft /></Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="flex h-[min(600px,70vh)] w-[min(320px,calc(100vw-32px))] flex-col overflow-hidden p-0">
            {children}
          </PopoverContent>
        </Popover>
      </div>
    );
  }
  return <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-divider bg-workspace-subtle">{children}</aside>;
}
