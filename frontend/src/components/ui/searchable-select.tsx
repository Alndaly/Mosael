import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Option = { value: string; label: string };

/**
 * 可搜索、限高的下拉——用于选项多到普通 Select 会溢出屏幕的场景(如 ComfyUI 的 checkpoint/采样器
 * 可能上百项)。Popover + cmdk:输入即过滤,列表封顶高度内滚动,宽度对齐触发器。
 *
 * Popover 必须带 `modal`:Dialog 用 react-remove-scroll 锁背景滚动,只放行自己 shard
 * (DialogContent)内的滚轮,而 PopoverContent 走 Portal 渲染到 body、落在 shard 之外——不加 modal
 * 时列表明明可滚、滚动条也在,滚轮却完全无效(拖滚动条/方向键仍可用,是这个故障的特征组合)。
 * 加了之后 Popover 自建滚动锁并把自己的内容作为放行区;对话框外的行为也一致(与原生 select 相同)。
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

export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder,
  searchPlaceholder,
  emptyText,
  className,
  disabled,
  trigger,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: Array<Option | string>;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  disabled?: boolean;
  /** 自定义触发器(替换默认按钮),用于像「添加节点」这类带图标/胶囊样式的触发器。 */
  trigger?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const modal = useInsideDialog(triggerRef);
  const items: Option[] = options.map((option) => (typeof option === "string" ? { value: option, label: option } : option));
  const selected = items.find((item) => item.value === value);
  return (
    <Popover modal={modal} open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {trigger ?? (
          <button ref={triggerRef}
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
        )}
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
                {/* 勾在右端、只在选中时渲染:左侧占位勾会让**每一行**都白缩进一个图标宽,
                    而「添加节点」这类当动作菜单用的场景根本没有选中项,那块缩进纯属浪费。 */}
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {item.value === value && <Check size={14} className="shrink-0 text-primary" />}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
