import React from "react";
import {
  BookOpen,
  Bot,
  CalendarClock,
  FolderOpen,
  Home,
  Languages,
  Layers,
  MonitorCog,
  Moon,
  Plug,
  Rocket,
  Scissors,
  Settings,
  Sun,
} from "lucide-react";

import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { MessageKey } from "@/app/messages";

export type StudioView =
  | "home"
  | "media"
  | "editor"
  | "ai"
  | "batch"
  | "publish"
  | "kb"
  | "settings"
  | "scheduler"
  | "plugins";

const PRIMARY_NAV: Array<{ view: StudioView; icon: React.ReactNode; labelKey: MessageKey }> = [
  { view: "home", icon: <Home size={17} />, labelKey: "navHome" },
  { view: "media", icon: <FolderOpen size={17} />, labelKey: "navMedia" },
  { view: "editor", icon: <Scissors size={17} />, labelKey: "navEditor" },
  { view: "ai", icon: <Bot size={17} />, labelKey: "navAi" },
  { view: "batch", icon: <Layers size={17} />, labelKey: "navBatch" },
  { view: "publish", icon: <Rocket size={17} />, labelKey: "navPublish" },
  { view: "kb", icon: <BookOpen size={17} />, labelKey: "navKb" },
  { view: "settings", icon: <Settings size={17} />, labelKey: "navSettings" },
];

const SECONDARY_NAV: Array<{ view: StudioView; icon: React.ReactNode; labelKey: MessageKey }> = [
  { view: "scheduler", icon: <CalendarClock size={17} />, labelKey: "schedulerTitle" },
  { view: "plugins", icon: <Plug size={17} />, labelKey: "pluginsTitle" },
];

export function AppShell({
  view,
  onViewChange,
  workspaceName,
  projectName,
  actions,
  children,
}: {
  view: StudioView;
  onViewChange: (view: StudioView) => void;
  workspaceName: string;
  projectName: string | null;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="rail-brand" aria-hidden>
          M
        </div>
        {PRIMARY_NAV.map((item) => (
          <RailButton
            key={item.view}
            label={t(item.labelKey)}
            active={view === item.view}
            onClick={() => onViewChange(item.view)}
          >
            {item.icon}
          </RailButton>
        ))}
        <div className="rail-divider" />
        {SECONDARY_NAV.map((item) => (
          <RailButton
            key={item.view}
            label={t(item.labelKey)}
            active={view === item.view}
            onClick={() => onViewChange(item.view)}
          >
            {item.icon}
          </RailButton>
        ))}
        <div className="rail-spacer" />
      </aside>
      <div className="shell-main">
        <header className="topbar">
          <div className="topbar-crumb">
            <span>{workspaceName}</span>
            {projectName ? (
              <>
                <span className="topbar-sep">/</span>
                <strong>{projectName}</strong>
              </>
            ) : (
              <>
                <span className="topbar-sep">/</span>
                <span>{t("noProject")}</span>
              </>
            )}
          </div>
          <div className="topbar-actions">
            {actions}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light")}
                  aria-label={t("settingsTheme")}
                >
                  {theme === "light" ? <Sun size={15} /> : theme === "dark" ? <Moon size={15} /> : <MonitorCog size={15} />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {theme === "light" ? t("themeLight") : theme === "dark" ? t("themeDark") : t("themeSystem")}
              </TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")}
                  aria-label={locale === "zh-CN" ? "Switch to English" : "切换到中文"}
                >
                  <Languages size={15} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{locale === "zh-CN" ? "English" : "中文"}</TooltipContent>
            </Tooltip>
          </div>
        </header>
        <main className="shell-content">{children}</main>
      </div>
    </div>
  );
}

function RailButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={active ? "rail-btn active" : "rail-btn"}
          onClick={onClick}
          aria-label={label}
          aria-current={active ? "page" : undefined}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}
