import React from "react";

import { TAB_TRIGGER } from "@/components/ui/tabs";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type WorkbenchTab<T extends string> = { value: T; label: string; icon: React.ReactNode };

/**
 * 工作台右栏那一排页签:和别处的页签同一个样子(TAB_TRIGGER:14px、不折行、选中强调色字 + 2px 底线;整条 44px、下面一条分隔线)。
 *
 * 维护者:英文界面里「Run & results」折成了两行 —— 五个页签各带图标,默认 420px 宽的列放不下全部名字,此前的按钮又允许折行,
 * 于是最长的那个变成两行、把整条撑高。现在名字不折行;**放不下时没选中的那几个只剩图标**(名字在悬停说明和读屏里),
 * 选中的那个始终带名字。放不放得下按真宽度量(藏着一排带全部名字的影子,和列宽比),中文、英文、拖窄拖宽都一样判。
 */
export function WorkbenchTabs<T extends string>({
  tabs,
  active,
  onSelect,
  label,
  idPrefix,
}: {
  tabs: WorkbenchTab<T>[];
  active: T;
  onSelect: (tab: T) => void;
  label: string;
  /** 页签 / 面板的 id 前缀(`${idPrefix}-tab-${value}`、`${idPrefix}-panel-${value}`)。 */
  idPrefix: string;
}) {
  const listRef = React.useRef<HTMLDivElement>(null);
  const fullRef = React.useRef<HTMLDivElement>(null);
  const compact = useOverflows(listRef, fullRef, tabs.map((tab) => tab.label).join("\n"));
  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      data-workbench-tabs={compact ? "compact" : "full"}
      className="relative flex h-11 flex-none items-stretch gap-0.5 overflow-hidden border-b border-border px-1.5"
    >
      {/* 影子:带全部名字的那一排有多宽。不可见、不占位、不进读屏。 */}
      <div ref={fullRef} aria-hidden className="pointer-events-none invisible absolute left-0 top-0 flex h-full w-max gap-0.5 px-1.5">
        {tabs.map((tab) => (
          <span key={tab.value} className={cn(TAB_TRIGGER, "px-1.5 [&_svg]:size-4")}>
            {tab.icon}
            {tab.label}
          </span>
        ))}
      </div>
      {tabs.map((tab) => {
        const selected = tab.value === active;
        const iconOnly = compact && !selected;
        const button = (
          <button
            key={tab.value}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${tab.value}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${tab.value}`}
            aria-label={iconOnly ? tab.label : undefined}
            data-workbench-tab={tab.value}
            className={cn(TAB_TRIGGER, "px-1.5 [&_svg]:size-4")}
            onClick={() => onSelect(tab.value)}
          >
            {tab.icon}
            {!iconOnly && tab.label}
          </button>
        );
        return iconOnly ? (
          <Hint key={tab.value} label={tab.label}>
            {button}
          </Hint>
        ) : (
          button
        );
      })}
    </div>
  );
}

/** 影子那一排比列宽:放不下。列宽变了(拖、开关窗口)、名字变了(换语言)重新量。 */
function useOverflows(list: React.RefObject<HTMLElement | null>, full: React.RefObject<HTMLElement | null>, labels: string): boolean {
  const [overflows, setOverflows] = React.useState(false);
  React.useLayoutEffect(() => {
    const row = list.current;
    const shadow = full.current;
    if (!row || !shadow) return;
    const check = () => setOverflows(shadow.scrollWidth > row.clientWidth);
    check();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(check);
    observer.observe(row);
    return () => observer.disconnect();
  }, [list, full, labels]);
  return overflows;
}
