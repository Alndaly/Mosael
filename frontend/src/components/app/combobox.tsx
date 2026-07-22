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
          className={cn("justify-between", className)}
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
              <CommandItem key={option.value} value={option.value} onSelect={() => choose(option.value)}>
                <Check className={cn("size-4", option.value === value ? "opacity-100" : "opacity-0")} />
                <span className="truncate">{option.label ?? option.value}</span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
