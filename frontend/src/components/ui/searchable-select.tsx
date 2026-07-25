import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Option = { value: string; label: string };

/**
 * 可搜索、限高的下拉——用于选项多到普通 Select 会溢出屏幕的场景(如 ComfyUI 的 checkpoint/采样器
 * 可能上百项)。Popover + cmdk:输入即过滤,列表封顶高度内滚动,宽度对齐触发器。
 */
export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder,
  emptyText,
  className,
  disabled,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: Array<Option | string>;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const items: Option[] = options.map((option) => (typeof option === "string" ? { value: option, label: option } : option));
  const selected = items.find((item) => item.value === value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          className={cn(
            "flex h-8 w-full items-center justify-between gap-1 rounded-md border border-input bg-field px-2.5 text-[12.5px] text-foreground focus-visible:border-primary focus-visible:outline-none disabled:cursor-default disabled:opacity-50",
            className,
          )}
        >
          <span className="truncate">{selected?.label ?? placeholder ?? ""}</span>
          <ChevronDown size={14} className="shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command>
          <CommandInput placeholder={searchPlaceholder ?? "搜索…"} className="h-9" />
          <CommandList className="max-h-[240px]">
            <CommandEmpty>{emptyText ?? "无匹配项"}</CommandEmpty>
            {items.map((item) => (
              <CommandItem
                key={item.value}
                value={item.label}
                onSelect={() => {
                  onValueChange(item.value);
                  setOpen(false);
                }}
              >
                <Check size={14} className={cn("mr-2 shrink-0", item.value === value ? "opacity-100" : "opacity-0")} />
                <span className="truncate">{item.label}</span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
