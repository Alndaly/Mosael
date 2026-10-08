import React from "react";
import { cn } from "@/lib/utils";

/** The page owns its title, description and primary action; collections own their filters. */
export function PageHeading({ title, description, count, actions, className }: {
  title: string; description?: string; count?: number; actions?: React.ReactNode; className?: string;
}) {
  return <header data-slot="page-heading" className={cn("flex shrink-0 flex-wrap items-end justify-between gap-x-8 gap-y-4", className)}>
    <div className="min-w-0">
      <div className="flex items-center gap-3"><h2 className="m-0 text-ui-title font-semibold leading-tight tracking-tight">{title}</h2>{count !== undefined && <span className="rounded-md bg-secondary px-2 py-1 text-ui-sm tabular-nums text-muted-foreground">{count}</span>}</div>
      {description && <p className="mb-0 mt-2 max-w-2xl text-ui-sm leading-relaxed text-muted-foreground">{description}</p>}
    </div>
    {actions && <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div>}
  </header>;
}

/** 列表页的卡片网格。**三个列表页共用同一串** —— 画板、工作流、3D 场景并排时,卡片该是一样宽、
 *  行列该是一样疏。此前 3D 场景自己写了一份(最小列宽 240 而不是 280、gap 一个数而不是分行列,
 *  外加一个 margin-top 叠在页面自己的间距上),于是它的卡片更窄、列更多、离页头更远。 */
export const CARD_GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(100%,280px),1fr))] gap-x-6 gap-y-8";

export const STUDIO_PAGE = "flex h-full min-h-0 flex-col gap-7 overflow-auto px-6 py-7 xl:px-9 xl:py-8 [&>*]:shrink-0";

/** A compact, keyboard-accessible choice strip; selection is explicit even without color. */
/**
 * 页面顶上那一排页签(管理、统计、素材、首页、资产……)。**和插件详情、资产详情用的 Radix Tabs 同一种语义**:
 * 读屏念成「页签 · 已选中」,Tab 只停在选中的那一个,左右方向键换、Home / End 到头尾,换到哪个就切到哪个。
 * 此前这里是一组 `aria-pressed` 按钮:相邻页面上键盘要换两套操作、读屏念成两种东西(体检 UM-34)。
 */
export function CollectionTabs<T extends string>({ value, onChange, items, label }: {
  value: T; onChange: (value: T) => void; items: { value: T; label: string; count?: number }[]; label: string;
}) {
  const refs = React.useRef<Array<HTMLButtonElement | null>>([]);
  //: 值不在清单里(还没归一化的那一帧)时,让第一个能被 Tab 到 —— 否则整排都是 -1,键盘进不来。
  const focusable = Math.max(0, items.findIndex((item) => item.value === value));
  const select = (index: number) => {
    const at = (index + items.length) % items.length;
    onChange(items[at].value);
    refs.current[at]?.focus();
  };
  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    const target = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: items.length - 1 }[event.key];
    if (target === undefined) return;
    event.preventDefault();
    select(target);
  };
  return <div role="tablist" aria-label={label} aria-orientation="horizontal" className="flex min-w-0 gap-5 overflow-x-auto">
    {items.map((item, index) => <button
      key={item.value}
      ref={(element) => { refs.current[index] = element; }}
      type="button"
      role="tab"
      aria-label={`${item.label}${item.count !== undefined ? ` ${item.count}` : ""}`}
      aria-selected={value === item.value}
      tabIndex={index === focusable ? 0 : -1}
      onClick={() => onChange(item.value)}
      onKeyDown={(event) => onKeyDown(event, index)}
      className={cn("flex h-10 shrink-0 cursor-pointer items-center gap-2 border-b-2 border-transparent px-1 text-ui-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset", value === item.value && "border-primary text-primary")}
    >
      {item.label}{item.count !== undefined && <span className="text-ui-xs tabular-nums text-muted-foreground">{item.count}</span>}
    </button>)}
  </div>;
}
