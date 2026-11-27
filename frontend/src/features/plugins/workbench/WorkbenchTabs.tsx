import React from "react";

import { TAB_TRIGGER } from "@/components/ui/tabs";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type WorkbenchTab<T extends string> = {
  value: T;
  label: string;
  icon: React.ReactNode;
  /** 这个页签里有多少件要看的事(缺的节点 + 缺的模型):>0 时挂一个数字徽标。 */
  count?: number;
};

/**
 * 工作台右栏那一排页签:和别处的页签同一个样子(TAB_TRIGGER:14px、不折行、选中强调色字 + 2px 底线;整条 44px、下面一条分隔线)。
 *
 * 这一列只放图标:中文、英文的名字都收进 `aria-label` 和悬停说明,页签不再撑宽,也不出现「选中才带名字」的跳动。
 * 数字徽标照旧露在外面。键盘和读屏拿到的仍是完整名字,图标不是唯一信息。
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
  return (
    <div
      role="tablist"
      aria-label={label}
      data-workbench-tabs="icons"
      className="relative flex h-11 flex-none items-stretch gap-0.5 overflow-hidden border-b border-border px-1.5"
    >
      {tabs.map((tab) => {
        const selected = tab.value === active;
        const name = tab.count ? `${tab.label} (${tab.count})` : tab.label;
        return (
          <Hint key={tab.value} label={name}>
            <button
              type="button"
              role="tab"
              id={`${idPrefix}-tab-${tab.value}`}
              aria-selected={selected}
              aria-controls={`${idPrefix}-panel-${tab.value}`}
              aria-label={name}
              data-workbench-tab={tab.value}
              className={cn(TAB_TRIGGER, "px-1.5 [&_svg]:size-4")}
              onClick={() => onSelect(tab.value)}
            >
              {tab.icon}
              {badge(tab.count)}
            </button>
          </Hint>
        );
      })}
    </div>
  );
}

/** 页签上的数字徽标:缺东西时不再静默(图标不遮住它)。 */
function badge(count: number | undefined): React.ReactNode {
  if (!count) return null;
  return (
    <span data-tab-count="" aria-hidden
          className="ml-1 inline-flex min-w-4 shrink-0 items-center justify-center rounded-full bg-warning/15 px-1 text-ui-2xs font-semibold tabular-nums text-warning">
      {count > 99 ? "99+" : count}
    </span>
  );
}
