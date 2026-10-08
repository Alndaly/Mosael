import React from "react";
import { ShieldCheck } from "lucide-react";

import { gotoAdmin, useOpenRequest } from "@/lib/deepLink";
import type { Workspace } from "@/api/client";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { COMPACT_SIDEBAR_BOUNDS, useResizableSidebar } from "@/lib/useResizableSidebar";
import { SettingsSectionStack } from "@/components/settings/settings-layout";
import {
  ALL_SECTIONS,
  DEFAULT_SECTION_ID,
  SETTINGS_GROUPS,
  resolveSettingsLink,
} from "@/features/settings/settingsSections";
import { ADMIN_SETTINGS, SETTINGS_SEARCH, matchSettings } from "@/lib/settingsSearch";

const SECTION_STORAGE_KEY = "mosael:settings-section";

/**
 * 设置页的外壳:左边导航、右边当前页。**它不认识任何一页** —— 有哪些页、怎么分组、每页渲染
 * 什么,全在 settingsSections.tsx 那一份声明里。加一页只动那里。
 */
export function SettingsView({ workspace }: { workspace: Workspace }) {
  // 导航项是短标签,不是长内容 —— 用紧凑档,宽度让给右边真正在配的东西。
  const sidebar = useResizableSidebar("settings", COMPACT_SIDEBAR_BOUNDS);
  const t = useI18n();
  const isDeploymentAdmin = useIsDeploymentAdmin();
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
  useOpenRequest("mosael:open-settings", (link) => {
    const target = resolveSettingsLink(link);
    if (!target) return;
    setSection(target.id);
    setFocusCapability(target.focus);
  });

  //: 搜的不只是分区名,还有分区里那些行(「主题」「密码」「默认模型」)和只在管理页的设置(「代理」「镜像」「邀请码」),
  //: 见 settingsSearch。此前只比分区名,按「我要改什么」来搜几乎都是「没有找到」(体检 UM-15)。
  const sectionHits = new Map(matchSettings(SETTINGS_SEARCH, navSearch, t).map(({ entry, hit }) => [entry.id, hit]));
  const adminHits = navSearch.trim() ? matchSettings(ADMIN_SETTINGS, navSearch, t) : [];
  const current = ALL_SECTIONS.find((one) => one.id === section) ?? ALL_SECTIONS[0];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-workspace-panel">
      <div className="relative grid min-h-0 flex-1 grid-cols-[var(--studio-index-width)_minmax(0,1fr)] max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]" style={{ "--studio-index-width": `${sidebar.width}px` } as React.CSSProperties}>
        <nav className="flex min-h-0 flex-col gap-5 overflow-y-auto border-r border-divider bg-workspace-subtle px-4 py-5 max-[880px]:max-h-48 max-[880px]:border-b max-[880px]:border-r-0" aria-label={t("settingsTitle")}>
          <Input className="shrink-0" aria-label={t("studioSettingsSearch")} placeholder={t("studioSettingsSearch")} value={navSearch} onChange={e => setNavSearch(e.target.value)} />
          {SETTINGS_GROUPS.map((group) => {
            const items = group.sections.filter((one) => sectionHits.has(one.id));
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
                    <span className="min-w-0">
                      {t(item.label)}
                      {sectionHits.get(item.id) && <span className="text-ui-xs font-normal text-muted-foreground"> · {t(sectionHits.get(item.id)!)}</span>}
                    </span>
                  </button>
                ))}
              </div>
            );
          })}
          {adminHits.length > 0 && (
            <div className="grid gap-1" data-settings-admin-hits="">
              <h3 className="m-0 px-2 pb-1 text-ui-xs font-medium text-muted-foreground">{t("settingsSearchInAdmin")}</h3>
              {adminHits.map(({ entry }) =>
                isDeploymentAdmin ? (
                  <button
                    key={entry.id}
                    type="button"
                    className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-left text-ui-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => gotoAdmin(entry.tab)}
                  >
                    <ShieldCheck size={14} />
                    <span>{t(entry.label)}</span>
                  </button>
                ) : (
                  <div key={entry.id} className="grid gap-0.5 px-2 py-1.5 text-ui-sm text-muted-foreground">
                    <span>{t(entry.label)}</span>
                    <small className="text-ui-xs leading-normal">{t("settingsSearchAdminOnly")}</small>
                  </div>
                ),
              )}
            </div>
          )}
          {sectionHits.size === 0 && adminHits.length === 0 && (
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
