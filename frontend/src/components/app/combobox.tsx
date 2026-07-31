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

/**
 * 只在**确实位于 Dialog 内**时才开 modal。
 *
 * modal 是为了解决 Dialog 专属的问题:Dialog 用 react-remove-scroll 锁背景滚动,只放行自己
 * shard 内的滚轮,而 PopoverContent 走 Portal 落在 shard 之外 —— 不加 modal 就滚不动列表。
 *
 * 但 modal 会让 Radix 给 `document.body` 挂上 `pointer-events: none`,而这个还原**并不可靠**
 * (多层 Popper 交替开关时会漏)。留下来的后果是**整个应用点击穿透** —— 表现为「点面板上的
 * 输入框,却选中了它背后的画布节点」,而且看不出跟下拉框有任何关系。
 *
 * 所以按位置决定:Dialog 内需要它,Dialog 外不该为它付这个代价。
 */
function useInsideDialog(ref: React.RefObject<HTMLElement | null>): boolean {
  const [inside, setInside] = React.useState(false);
  React.useEffect(() => {
    setInside(Boolean(ref.current?.closest('[role="dialog"]')));
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
  const canUseCustom =
    allowCustomValue && Boolean(trimmedQuery) && !options.some((option) => option.value === trimmedQuery);

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
        <Button
          ref={triggerRef}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn("justify-between rounded-md border-input bg-field font-normal hover:bg-field hover:text-foreground", className)}
        >
          {/* min-w-0:flex 子项默认 min-width:auto,不肯收缩 —— truncate 就失效,
              长模型名会顶穿按钮边框、把右侧箭头挤没。 */}
          <span className={cn("min-w-0 truncate", value ? "text-foreground" : "text-muted-foreground")}>
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
