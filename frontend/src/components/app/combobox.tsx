import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { FIELD_TRIGGER_CLASS, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger"
import { insideDialog } from "@/components/ui/insideDialog";
import { cn } from "@/lib/utils";

export type ComboboxOption = {
  value: string;
  label?: string;
};

/**
 * 为什么 Popover 必须带 `modal`(不是可选优化):
 *
 * Dialog 用 react-remove-scroll 锁背景滚动,而它**只放行自己 shard(DialogContent)内**的滚轮事件。
 * PopoverContent 走 Portal 渲染到 body,天然落在 shard 之外 —— 于是列表明明是 overflow-y-auto、
 * 滚动条也画出来了,滚轮却完全无效(拖滚动条、按方向键仍可用,这个组合就是它的特征)。
 *
 * 加上 modal 后 Popover 自己建立滚动锁,并把自己的内容作为放行区,列表就能滚。在对话框外用也一致:
 * 打开期间锁住背景滚动,与原生 select 的行为相同。
 */

function useInsideDialog(ref: React.RefObject<HTMLElement | null>): boolean {
  const [inside, setInside] = React.useState(false);
  React.useEffect(() => {
    setInside(insideDialog(ref.current));
  });
  return inside;
}

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
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const modal = useInsideDialog(triggerRef);
  const [query, setQuery] = React.useState("");
  const selected = options.find((option) => option.value === value);
  const trimmedQuery = query.trim();
  // 认 label 也认 value:显示名和真实值不一样时(如 `source_video.asset_id` 背后存的是
  // `{{source_video.asset_id}}`),照着屏幕上的字打一遍不该被当成"自己新写的字面量"。
  const canUseCustom =
    allowCustomValue &&
    Boolean(trimmedQuery) &&
    !options.some((option) => option.value === trimmedQuery || option.label === trimmedQuery);

  const choose = (nextValue: string) => {
    onValueChange(nextValue);
    setQuery("");
    setOpen(false);
  };

  return (
    // modal 见组件顶部注释:不加就在对话框里滚不动。
    <Popover
      modal={modal}
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        {/* 不用 <Button variant="outline">:它的默认尺寸是 rounded-full px-4 的胶囊,
            和旁边的 Select 并排时圆角、左右留白、箭头全都对不上。共用 FIELD_TRIGGER_CLASS。 */}
        <button
          ref={triggerRef}
          type="button"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(FIELD_TRIGGER_CLASS, "cursor-pointer text-left", className)}
        >
          <span className={value ? "text-foreground" : "text-muted-foreground"}>
            {selected?.label ?? (value || placeholder)}
          </span>
          <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
        </button>
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
