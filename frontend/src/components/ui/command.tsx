import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const Command = CommandPrimitive;
const CommandEmpty = CommandPrimitive.Empty;

/** Cmd+K 弹层:顶部 1/5 处的宽输入面板(Revornix 同款骨架,Mibu 全平面样式)。 */
function CommandDialog({
  open,
  onOpenChange,
  label,
  shouldFilter,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  shouldFilter?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showClose={false}
        className={cn(
          "top-[18%] z-50 w-[min(620px,calc(100vw-48px))] overflow-hidden rounded-xl border-border-strong p-0",
        )}
      >
        <DialogTitle className="sr-only">{label}</DialogTitle>
        <Command label={label} shouldFilter={shouldFilter}>
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function CommandInput({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex items-center gap-2 border-b border-border px-3.5">
      <Search size={14} className="shrink-0 text-muted-foreground" />
      <CommandPrimitive.Input
        className={cn(
          "h-11 w-full bg-transparent text-[13.5px] text-foreground outline-none placeholder:text-muted-foreground",
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      className={cn("max-h-[min(420px,60vh)] overflow-y-auto p-1.5", className)}
      {...props}
    />
  );
}

function CommandGroup({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      className={cn(
        "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10.5px]",
        "[&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase",
        "[&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2.5 rounded-md px-2 py-2 text-[12.5px] text-foreground",
        "outline-none data-[selected=true]:bg-secondary",
        className,
      )}
      {...props}
    />
  );
}

function CommandSeparator({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Separator>) {
  return <CommandPrimitive.Separator className={cn("my-1 h-px bg-border", className)} {...props} />;
}

export { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator };
