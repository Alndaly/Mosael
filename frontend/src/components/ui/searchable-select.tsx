import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Option = {
  value: string;
  label: string;
  /** 副标题,灰色小字排在标签下面。用来解释"这一项是干什么的"。 */
  description?: string;
  /** 分组标题。相邻的同名项归一组;顺序即传入顺序,这里不排序 —— 谁提供选项,谁决定顺序。 */
  group?: string;
};

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
  const hasDescriptions = items.some((item) => item.description);
  // 按**相邻**的同名 group 归组,不重排 —— 提供选项的一方已经排好了顺序(节点面板的
  // 分组顺序来自后端的 NODE_CATEGORIES),这里再排一次就成了第二份要维护的顺序。
  const groups = React.useMemo(() => {
    const out: Array<[string, Option[]]> = [];
    for (const item of items) {
      const heading = item.group ?? "";
      const last = out[out.length - 1];
      if (last && last[0] === heading) last[1].push(item);
      else out.push([heading, [item]]);
    }
    return out;
  }, [items]);
  return (
    <Popover modal={modal} open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {trigger ?? (
          <button ref={triggerRef}
            type="button"
            disabled={disabled}
            className={cn(
              "flex h-8 w-full min-w-0 items-center justify-between gap-1 rounded-md border border-input bg-field px-2.5 text-[12.5px] text-foreground focus-visible:border-primary focus-visible:outline-none disabled:cursor-default disabled:opacity-50",
              className,
            )}
          >
            {/* min-w-0:flex 子项默认不肯收缩,truncate 会失效(见 field-trigger.ts)。
                未选中时走 placeholder 色:和输入框的 placeholder 同一个视觉约定 —— 用正文色
                写「平台」,读起来像是**已经选了**一个叫「平台」的东西。 */}
            <span className={cn("min-w-0 truncate", !selected && "text-muted-foreground")}>
              {selected?.label ?? placeholder ?? ""}
            </span>
            <ChevronDown size={14} className="shrink-0 opacity-50" />
          </button>
        )}
      </PopoverTrigger>
      {/* 宽度:普通下拉对齐触发器;**带描述时改用固定宽度**。
          对齐触发器的前提是"选项跟触发器差不多长",而描述行是整整一句话 —— 「添加节点」的
          触发器只有一枚胶囊那么宽,列表若跟着它就每行都得折成三行;反过来放开让内容撑,
          一句长描述能把浮层顶到整屏宽(实测就是如此)。给个够读一行的固定宽度,超出截断。 */}
      <PopoverContent
        className={cn("p-0", hasDescriptions ? "w-[360px] max-w-[calc(100vw-24px)]" : "w-[--radix-popover-trigger-width]")}
        align="start"
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder ?? "搜索…"} className="h-9" />
          <CommandList className="max-h-[300px]">
            <CommandEmpty>{emptyText ?? "无匹配项"}</CommandEmpty>
            {groups.map(([heading, groupItems]) => {
              const rows = groupItems.map((item) => (
                <CommandItem
                  key={item.value}
                  // 描述也参与搜索:用户记得住"发抖音"却未必记得节点叫「发布」。
                  value={`${item.label} ${item.description ?? ""}`}
                  onSelect={() => {
                    onValueChange(item.value);
                    setOpen(false);
                  }}
                >
                  {/* 勾在右端、只在选中时渲染:左侧占位勾会让**每一行**都白缩进一个图标宽,
                      而「添加节点」这类当动作菜单用的场景根本没有选中项,那块缩进纯属浪费。 */}
                  <span className="grid min-w-0 flex-1 gap-px leading-[1.35]">
                    <span className="truncate">{item.label}</span>
                    {item.description && (
                      <span className="truncate text-[11px] text-muted-foreground">{item.description}</span>
                    )}
                  </span>
                  {item.value === value && <Check size={14} className="shrink-0 text-primary" />}
                </CommandItem>
              ));
              return heading ? (
                <CommandGroup key={heading} heading={heading}>
                  {rows}
                </CommandGroup>
              ) : (
                <React.Fragment key="__ungrouped">{rows}</React.Fragment>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
