import React from "react";
import {
  BookOpen,
  Bot,
  CalendarClock,
  Check,
  ChevronsUpDown,
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

import type { Workspace } from "@/api/client";
import { useAuth } from "@/app/auth";
import { displayWorkspaceName, useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NotificationCenter } from "@/components/layout/NotificationCenter";
import { TaskCenter } from "@/components/layout/TaskCenter";
import { BrandMark } from "@/components/layout/BrandMark";
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

/** 只有「剪辑」工作在"当前项目"语境 —— 它编辑的就是某个项目的时间线。
    其余页面的面包屑显示页面名,否则设置/插件页也挂着项目名,既不合理也容易误解。
    「素材」是**工作区级**资源池(素材属于工作区,project_id 可空且删项目只置空)。
    「AI 助手」同理是工作区级:智能体本身就能跨项目管理(列项目、改时间线都是它的工具),
    把会话锁在"当前项目"是把关系搞反了 —— 它是项目的操作者,不是项目的附属物。 */
const PROJECT_SCOPED_VIEWS: StudioView[] = ["editor"];

export function AppShell({
  view,
  onViewChange,
  workspaceId,
  workspaceName,
  workspaces = [],
  onSelectWorkspace,
  projectName,
  actions,
  children,
}: {
  view: StudioView;
  onViewChange: (view: StudioView) => void;
  workspaceId?: string;
  workspaceName: string;
  workspaces?: Workspace[];
  onSelectWorkspace?: (id: string) => void;
  projectName: string | null;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();

  return (
    <div className="app-shell">
      <header className="topbar">
        {(() => {
          // 面包屑必须始终暴露"当前页面";项目语境的页面再把项目名接成第三段。
          // 早先的写法在 media/editor/ai 无项目时只显示"还没有项目",页面身份被抹掉
          // (三个项目页面看起来一模一样),这里修正。页面名是本页唯一的 h1。
          const pageLabel = t(
            [...PRIMARY_NAV, ...SECONDARY_NAV].find((item) => item.view === view)?.labelKey ?? "navHome",
          );
          const scoped = PROJECT_SCOPED_VIEWS.includes(view);
          return (
            <div className="topbar-crumb">
              <WorkspaceSwitcher
                workspaceId={workspaceId}
                workspaceName={workspaceName}
                workspaces={workspaces}
                onSelectWorkspace={onSelectWorkspace}
              />
              <span className="topbar-sep">/</span>
              <h1 className={scoped ? "topbar-crumb-page muted" : "topbar-crumb-page"}>{pageLabel}</h1>
              {scoped && (
                <>
                  <span className="topbar-sep">/</span>
                  {projectName ? (
                    <strong className="topbar-crumb-leaf">{projectName}</strong>
                  ) : (
                    <span className="topbar-crumb-hint">{t("crumbNoProject")}</span>
                  )}
                </>
              )}
            </div>
          );
        })()}
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
                size="icon"
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
                size="icon"
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
      <aside className="rail">
        <div className="rail-brand" aria-hidden>
          <BrandMark size={22} />
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
      <main className="shell-content">{children}</main>
    </div>
  );
}

/** 面包屑首段的工作区切换器。单一工作区时退化为纯文本(无多余下拉);
    多工作区时给一个 Popover 列表——这样任务/项目落在非首个工作区里也能被切回去。 */
function WorkspaceSwitcher({
  workspaceId,
  workspaceName,
  workspaces,
  onSelectWorkspace,
}: {
  workspaceId?: string;
  workspaceName: string;
  workspaces: Workspace[];
  onSelectWorkspace?: (id: string) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);

  if (workspaces.length < 2 || !onSelectWorkspace) {
    return <span className="topbar-crumb-ws">{displayWorkspaceName(workspaceName, t)}</span>;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="topbar-crumb-ws topbar-ws-trigger" aria-label={t("workspaceSwitch")}>
          {displayWorkspaceName(workspaceName, t)}
          <ChevronsUpDown size={12} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="topbar-ws-pop" align="start" sideOffset={8}>
        <div className="topbar-ws-head">{t("workspaceSwitch")}</div>
        {workspaces.map((ws) => (
          <button
            key={ws.id}
            type="button"
            className={ws.id === workspaceId ? "topbar-ws-item active" : "topbar-ws-item"}
            onClick={() => {
              setOpen(false);
              if (ws.id !== workspaceId) onSelectWorkspace(ws.id);
            }}
          >
            <span className="topbar-ws-name">{displayWorkspaceName(ws.name, t)}</span>
            {ws.id === workspaceId && <Check size={13} />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/** 侧栏底部的用户入口:头像(用户名首字)→ 账号菜单 + 版本号。 */
function RailUserMenu({ onOpenSettings }: { onOpenSettings: () => void }) {
  const t = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const displayName = user?.display_name || user?.username || "user";
  const initial = displayName.slice(0, 1).toUpperCase();

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="rail-user" aria-label={displayName}>
          {initial}
        </button>
      </PopoverTrigger>
      <PopoverContent className="rail-user-pop" side="right" align="end" sideOffset={10}>
        <div className="rail-user-head">
          <span className="rail-user-avatar">{initial}</span>
          <div className="rail-user-names">
            <strong>{displayName}</strong>
            <small>{user?.username ? `@${user.username} · ${t("railLocalAccount")}` : t("railLocalAccount")}</small>
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
