import * as React from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type ComboboxOption = {
  value: string;
  label?: string;
};

export function Combobox({
  value,
  options,
  placeholder,
  searchPlaceholder,
  emptyText = "没有匹配项",
  allowCustomValue = false,
  customValueLabel = (query) => `使用 “${query}”`,
  disabled,
  className,
  contentClassName,
  onValueChange,
}: {
  value: string;
  options: ComboboxOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  allowCustomValue?: boolean;
  customValueLabel?: (query: string) => string;
  disabled?: boolean;
  className?: string;
  contentClassName?: string;
  onValueChange: (value: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const selected = options.find((option) => option.value === value);
  const trimmedQuery = query.trim();
  const canUseCustom =
    allowCustomValue && Boolean(trimmedQuery) && !options.some((option) => option.value === trimmedQuery);

  const choose = (nextValue: string) => {
    onValueChange(nextValue);
    setQuery("");
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn("justify-between rounded-md border-input bg-field font-normal hover:bg-field hover:text-foreground", className)}
        >
          <span className={cn("truncate", value ? "text-foreground" : "text-muted-foreground")}>
            {selected?.label ?? (value || placeholder)}
          </span>
          <ChevronsUpDown size={14} className="shrink-0 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className={cn("w-[var(--radix-popover-trigger-width)] p-0", contentClassName)} align="start">
        <Command shouldFilter>
          <CommandInput value={query} onValueChange={setQuery} placeholder={searchPlaceholder ?? placeholder} />
          <CommandList>
            {canUseCustom ? (
              <CommandItem value={`custom-${trimmedQuery}`} onSelect={() => choose(trimmedQuery)}>
                <span className="truncate">{customValueLabel(trimmedQuery)}</span>
              </CommandItem>
            ) : null}
            <CommandEmpty>{emptyText}</CommandEmpty>
            {options.map((option) => (
              // cmdk 按 item 的 value 过滤:value 若只是 id(uuid),按名称搜索会一无所获。
              // label 打头让搜索命中名称,拼上 id 保证唯一。
              <CommandItem
                key={option.value}
                value={`${option.label ?? option.value} ${option.value}`}
                onSelect={() => choose(option.value)}
              >
                {/* 勾在右端、且只在选中时渲染。此前是左侧一个 opacity-0 的占位勾:为了"选中态切换时
                    文字不跳",代价是**每一行**都白缩进一个图标宽——而列表里最多只有一行是选中的,
                    放右边就既不跳也不缩进。 */}
                <span className="min-w-0 flex-1 truncate">{option.label ?? option.value}</span>
                {option.value === value && <Check className="size-4 shrink-0 text-primary" />}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
