import { ACTION_MENU } from "@/components/ui/floating";
import type { ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Action = {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
};

export function ActionMenu({ label, actions }: { label: string; actions: Action[] }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label}><MoreHorizontal /></Button>
      </PopoverTrigger>
      <PopoverContent align="end" className={cn(ACTION_MENU, "w-52")}>
        {actions.map(action => (
          <PopoverClose key={action.label} asChild>
            <Button
              variant="ghost"
              className={cn("justify-start", action.destructive && "text-destructive hover:text-destructive")}
              disabled={action.disabled}
              onClick={action.onSelect}
            >
              {action.icon}{action.label}
            </Button>
          </PopoverClose>
        ))}
      </PopoverContent>
    </Popover>
  );
}
