import React from "react";

import type { Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { COMPACT_SIDEBAR_BOUNDS, useResizableSidebar } from "@/lib/useResizableSidebar";
import { SettingsSectionStack } from "@/features/settings/ui";
import {
  ALL_SECTIONS,
  DEFAULT_SECTION_ID,
  SETTINGS_GROUPS,
  resolveSettingsLink,
} from "@/features/settings/settingsSections";

const SECTION_STORAGE_KEY = "mosael:settings-section";

/**
 * 设置页的外壳:左边导航、右边当前页。**它不认识任何一页** —— 有哪些页、怎么分组、每页渲染
 * 什么,全在 settingsSections.tsx 那一份声明里。加一页只动那里。
 */
export function SettingsView({ workspace }: { workspace: Workspace }) {
  // 导航项是短标签,不是长内容 —— 用紧凑档,宽度让给右边真正在配的东西。
  const sidebar = useResizableSidebar("settings", COMPACT_SIDEBAR_BOUNDS);
  const t = useI18n();
  const [navSearch, setNavSearch] = React.useState("");
  const [focusCapability, setFocusCapability] = React.useState<string | null>(null);
  const [section, setSectionState] = React.useState<string>(() => {
    const saved = localStorage.getItem(SECTION_STORAGE_KEY);
    return saved && ALL_SECTIONS.some((one) => one.id === saved) ? saved : DEFAULT_SECTION_ID;
  });
  // 刷新后回到同一页(和剪辑台同款)。
  const setSection = (id: string) => {
    localStorage.setItem(SECTION_STORAGE_KEY, id);
    setSectionState(id);
  };

  // 深链:别处(如工作流「模型未配置」提示)→ mosael:open-settings 直达对应页。
  React.useEffect(() => {
    const onOpen = (event: Event) => {
      const target = resolveSettingsLink((event as CustomEvent<string>).detail);
      if (!target) return;
      setSection(target.id);
      setFocusCapability(target.focus);
    };
    window.addEventListener("mosael:open-settings", onOpen);
    return () => window.removeEventListener("mosael:open-settings", onOpen);
  }, []);

  const query = navSearch.toLocaleLowerCase();
  const matches = (label: string) => label.toLocaleLowerCase().includes(query);
  const current = ALL_SECTIONS.find((one) => one.id === section) ?? ALL_SECTIONS[0];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-workspace-panel">
      <div className="relative grid min-h-0 flex-1 grid-cols-[var(--studio-index-width)_minmax(0,1fr)] gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]" style={{ "--studio-index-width": `${sidebar.width}px` } as React.CSSProperties}>
        <nav className="flex min-h-0 flex-col gap-5 overflow-y-auto border-r border-divider bg-workspace-subtle px-4 py-5 max-[880px]:max-h-48 max-[880px]:border-b max-[880px]:border-r-0" aria-label={t("settingsTitle")}>
          <Input className="shrink-0" aria-label={t("studioSettingsSearch")} placeholder={t("studioSettingsSearch")} value={navSearch} onChange={e => setNavSearch(e.target.value)} />
          {SETTINGS_GROUPS.map((group) => {
            const items = group.sections.filter((one) => matches(t(one.label)));
            if (items.length === 0) return null;
            return (
              <div key={group.title} className="grid gap-1">
                <h3 className="m-0 px-2 pb-1 text-ui-xs font-medium text-muted-foreground">{t(group.title)}</h3>
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={section === item.id ? "page" : undefined}
                    className={cn(
                      "flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-left text-ui-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      section === item.id && "bg-panel font-semibold text-primary shadow-sm",
                    )}
                    onClick={() => {
                      setFocusCapability(null);
                      setSection(item.id);
                    }}
                  >
                    {item.icon}
                    <span>{t(item.label)}</span>
                  </button>
                ))}
              </div>
            );
          })}
          {ALL_SECTIONS.every((one) => !matches(t(one.label))) && (
            <p className="text-ui-sm text-muted-foreground">{t("studioSettingsEmpty")}</p>
          )}
        </nav>
        {/* 边缘拖动 —— 和别处同一套(lib/useResizableSidebar)。 */}
        <div {...sidebar.handleProps} className={cn(sidebar.handleProps.className, "max-[880px]:hidden")} />
        {/* 右栏是**一块占满高度的面板**,内部滚动 —— 和插件页、定时任务页同一套。此前它跟着
            内容走,内容少时就是半截,而左边是个完整的带边框面板。 */}
        <SettingsSectionStack className="min-h-0 min-w-0 overflow-y-auto bg-workspace-panel px-6 py-7 xl:px-10">
          {current.render({ workspace, t, focusCapability })}
        </SettingsSectionStack>
      </div>
    </div>
  );
}
