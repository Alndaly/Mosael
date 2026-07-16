import React from "react";
import {
  BookOpen,
  Bot,
  CalendarClock,
  FolderOpen,
  Home,
  Languages,
  Layers,
  LogOut,
  MonitorCog,
  Moon,
  Plug,
  Rocket,
  Scissors,
  Search,
  Settings,
  Sun,
  Workflow,
} from "lucide-react";

import { useAuth } from "@/app/auth";
import { displayWorkspaceName, useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NotificationCenter } from "@/components/layout/NotificationCenter";
import { TaskCenter } from "@/components/layout/TaskCenter";
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
  | "workflows"
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
  { view: "workflows", icon: <Workflow size={17} />, labelKey: "navWorkflows" },
  { view: "scheduler", icon: <CalendarClock size={17} />, labelKey: "schedulerTitle" },
  { view: "plugins", icon: <Plug size={17} />, labelKey: "pluginsTitle" },
];

/** 只有这些页面工作在"当前项目"语境;其余页面的面包屑显示页面名,
    否则设置/插件页也挂着项目名,既不合理也容易误解。 */
const PROJECT_SCOPED_VIEWS: StudioView[] = ["media", "editor", "ai"];

export function AppShell({
  view,
  onViewChange,
  workspaceId,
  workspaceName,
  projectName,
  actions,
  children,
}: {
  view: StudioView;
  onViewChange: (view: StudioView) => void;
  workspaceId?: string;
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
        <RailUserMenu onOpenSettings={() => onViewChange("settings")} />
      </aside>
      <div className="shell-main">
        <header className="topbar">
          <div className="topbar-crumb">
            <span>{displayWorkspaceName(workspaceName, t)}</span>
            <span className="topbar-sep">/</span>
            <strong>
              {PROJECT_SCOPED_VIEWS.includes(view)
                ? projectName ?? t("noProject")
                : t([...PRIMARY_NAV, ...SECONDARY_NAV].find((item) => item.view === view)?.labelKey ?? "navHome")}
            </strong>
          </div>
          <div className="topbar-actions">
            {actions}
            <button
              type="button"
              className="topbar-search"
              onClick={() => window.dispatchEvent(new CustomEvent("mibu:open-cmdk"))}
            >
              <Search size={13} />
              <span>{t("cmdkTitle")}</span>
              <kbd>⌘K</kbd>
            </button>
            {workspaceId && <TaskCenter workspaceId={workspaceId} />}
            {workspaceId && <NotificationCenter workspaceId={workspaceId} />}
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

/** 侧栏底部的用户入口:头像(用户名首字)→ 账号菜单 + 版本号。 */
function RailUserMenu({ onOpenSettings }: { onOpenSettings: () => void }) {
  const t = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const initial = (user?.username ?? "?").slice(0, 1).toUpperCase();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="rail-user" aria-label={user?.username ?? "user"}>
          {initial}
        </button>
      </PopoverTrigger>
      <PopoverContent className="rail-user-pop" side="right" align="end" sideOffset={10}>
        <div className="rail-user-head">
          <span className="rail-user-avatar">{initial}</span>
          <div className="rail-user-names">
            <strong>{user?.username}</strong>
            <small>{t("railLocalAccount")}</small>
          </div>
        </div>
        <div className="rail-user-actions">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onOpenSettings();
            }}
          >
            <Settings size={13} /> {t("navSettings")}
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
          >
            <LogOut size={13} /> {t("signOut")}
          </button>
        </div>
        <div className="rail-user-version">Mibu v{__APP_VERSION__}</div>
      </PopoverContent>
    </Popover>
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
