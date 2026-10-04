import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { FieldSize } from "@/components/ui/control-size"
import { fieldTriggerClass, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger"
import { insideDialog } from "@/components/ui/insideDialog";
import { SEARCHABLE_CONTENT_WIDTH } from "@/components/ui/floating";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useI18n } from "@/app/preferences";
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
  emptyText,
  allowCustomValue = false,
  acceptsCustomValue,
  customValueLabel,
  extraOptions,
  renderValue,
  hint,
  disabled,
  className,
  size,
  contentClassName,
  onValueChange,
}: {
  value: string;
  options: ComboboxOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  allowCustomValue?: boolean;
  /** 清单之外**哪种**手填收(不给 = 什么都收)。节点表单里挑东西的下拉只收 `{{…}}` 引用:
   *  随手敲的一串字在那里是一个不存在的 id,只会在运行时报错。 */
  acceptsCustomValue?: (query: string) => boolean;
  customValueLabel?: (query: string) => string;
  /** 按这次敲的字现算的几项,排在清单最前(手填那一项之前)。值和显示名都由调用方给 ——
   *  比如敲 `report.json.verdict` 时给一项「引用 写运营诊断 · JSON · verdict」,存下去是 `{{report.json.verdict}}`。 */
  extraOptions?: (query: string) => ComboboxOption[];
  /** 触发器上怎么显示当前值;不给(或返回 undefined)就是选中项的显示名,不在清单里的照原样。 */
  renderValue?: (value: string) => React.ReactNode;
  /** 触发器的悬停说明(值的全称、引用出了什么问题)。 */
  hint?: string;
  disabled?: boolean;
  className?: string;
  /** 触发器档位,和 `<Input size>`、`<Button size>` 同一把尺。 */
  size?: FieldSize;
  contentClassName?: string;
  onValueChange: (value: string) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const modal = useInsideDialog(triggerRef);
  const [query, setQuery] = React.useState("");
  const selected = options.find((option) => option.value === value);
  const trimmedQuery = query.trim();
  const extras = trimmedQuery && extraOptions ? extraOptions(trimmedQuery) : [];
  // 认 label 也认 value:显示名和真实值不一样时(如 `source_video.asset_id` 背后存的是
  // `{{source_video.asset_id}}`),照着屏幕上的字打一遍不该被当成"自己新写的字面量"。
  const canUseCustom =
    allowCustomValue &&
    Boolean(trimmedQuery) &&
    (acceptsCustomValue?.(trimmedQuery) ?? true) &&
    ![...options, ...extras].some((option) => option.value === trimmedQuery || option.label === trimmedQuery);
  const shown = value ? renderValue?.(value) : undefined;

  const trigger = (
    <PopoverTrigger asChild>
      {/* 不用 <Button variant="outline">:它的默认尺寸是 rounded-full px-4 的胶囊,
          和旁边的 Select 并排时圆角、左右留白、箭头全都对不上。共用 fieldTriggerClass。 */}
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-expanded={open}
        disabled={disabled}
        className={cn(fieldTriggerClass(size), "cursor-pointer text-left", className)}
      >
        {shown !== undefined && shown !== null ? (
          <span className="text-foreground">{shown}</span>
        ) : (
          <Truncate className={value ? "text-foreground" : "text-muted-foreground"}>{selected?.label ?? (value || placeholder)}</Truncate>
        )}
        <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
      </button>
    </PopoverTrigger>
  );

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
      {hint ? <Hint label={hint}>{trigger}</Hint> : trigger}
      {/* 宽度规则在 floating.ts(SEARCHABLE_CONTENT_WIDTH):此前死等于触发器宽,窄格子下面挂一条只剩几个字的列表。 */}
      <PopoverContent className={cn(SEARCHABLE_CONTENT_WIDTH, "p-0", contentClassName)} align="start">
        <Command shouldFilter>
          <CommandInput value={query} onValueChange={setQuery} placeholder={searchPlaceholder ?? placeholder} />
          <CommandList>
            {extras.map((option) => (
              // 现算的项要躲过 cmdk 按字过滤:value 带上这次敲的字。
              <CommandItem key={`extra-${option.value}`} value={`${trimmedQuery} ${option.value}`} onSelect={() => choose(option.value)}>
                <Truncate className="flex-1">{option.label ?? option.value}</Truncate>
              </CommandItem>
            ))}
            {canUseCustom ? (
              <CommandItem value={`custom-${trimmedQuery}`} onSelect={() => choose(trimmedQuery)}>
                <Truncate>{customValueLabel ? customValueLabel(trimmedQuery) : t("comboboxUseCustomValue").replace("{q}", trimmedQuery)}</Truncate>
              </CommandItem>
            ) : null}
            <CommandEmpty>{emptyText ?? t("comboboxNoMatch")}</CommandEmpty>
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
                <Truncate className="flex-1">{option.label ?? option.value}</Truncate>
                {option.value === value && <Check className="size-4 shrink-0 text-primary" />}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
