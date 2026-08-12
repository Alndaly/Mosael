import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Bot,
  Boxes,
  CalendarClock,
  Check,
  ChevronsUpDown,
  FolderOpen,
  FolderPlus,
  Home,
  Languages,
  LogOut,
  MonitorCog,
  Moon,
  Plug,
  Rocket,
  Scissors,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";

import { api, createWorkspace, userAvatarUrl, type Workspace } from "@/api/client";
import { useAuth } from "@/app/auth";
import { displayWorkspaceName, useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NotificationCenter } from "@/components/layout/NotificationCenter";
import { TaskCenter } from "@/components/layout/TaskCenter";
import { BrandMark } from "@/components/layout/BrandMark";
import { RenameDialog } from "@/components/app/modals";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { MessageKey } from "@/app/messages";
import { NAV_ITEMS, navLabelKey, type StudioView } from "@/components/layout/navLabels";
import { cn } from "@/lib/utils";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";

export type { StudioView } from "@/components/layout/navLabels";

/** 图标是**侧栏**的事(面包屑不画图标),所以只有它留在这里;
    「哪些页面、各叫什么」在 navLabels 那一份里。 */
const ICONS: Record<StudioView, React.ReactNode> = {
  home: <Home size={17} />,
  media: <FolderOpen size={17} />,
  editor: <Scissors size={17} />,
  ai: <Bot size={17} />,
  publish: <Rocket size={17} />,
  settings: <Settings size={17} />,
  workflows: <Workflow size={17} />,
  "browser-pool": <Boxes size={17} />,
  scheduler: <CalendarClock size={17} />,
  plugins: <Plug size={17} />,
  admin: <ShieldCheck size={17} />,
};

const PRIMARY_NAV = NAV_ITEMS.filter((item) => item.group === "primary");
/** admin 那一格只对部署管理员显示。**藏起来的入口不是权限** —— 后端每条 /api/admin 路由
 *  各自把关,这里只是不给不相干的人添乱。 */
const SECONDARY_NAV = NAV_ITEMS.filter((item) => item.group === "secondary");
const ADMIN_NAV = NAV_ITEMS.filter((item) => item.group === "admin");

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
  projects = [],
  currentProjectId,
  onSwitchProject,
  onCreateProject,
  creatingProject,
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
  /** Projects (timelines) in the current workspace — powers the in-header timeline switcher. */
  projects?: { id: string; name: string }[];
  currentProjectId?: string | null;
  onSwitchProject?: (id: string) => void;
  onCreateProject?: () => void;
  creatingProject?: boolean;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useI18n();
  const { theme, setTheme, locale, setLocale } = usePreferences();
  // 管理入口只对部署管理员显示。**藏起来的入口不是权限** —— 后端每条 /api/admin 路由各自
  // 把关;这里只是不给不相干的人添乱。
  const me = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api<{ is_deployment_admin: boolean }>("/api/auth/me"),
  });
  const isDeploymentAdmin = me.data?.is_deployment_admin ?? false;

  // 桌面端启动静默更新检查的回报:有新版弹一条可点开发布页的提示(不打断)。
  React.useEffect(() => {
    return window.openStudioDesktop?.onUpdateAvailable?.((info) => {
      if (!info?.hasUpdate) return;
      toast(t("updateAvailable").replace("{version}", info.latest ?? ""), {
        duration: 12000,
        action: { label: t("updateView"), onClick: () => window.open(info.url, "_blank") },
      });
    });
  }, [t]);

  return (
    <div className="grid h-screen grid-cols-[56px_minmax(0,1fr)] grid-rows-[44px_minmax(0,1fr)]">
      <header className={cn(
        "col-span-full flex items-center justify-between border-b border-border bg-panel px-2.5 supports-[backdrop-filter]:bg-[var(--glass-chrome)] supports-[backdrop-filter]:[-webkit-backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] supports-[backdrop-filter]:[[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] [.is-desktop_&]:[-webkit-app-region:drag] [.is-desktop_&_:is(button,a,input,[role=button])]:[-webkit-app-region:no-drag]",
        WINDOW_CHROME_INSET,
      )}>
        {(() => {
          // 面包屑必须始终暴露"当前页面";项目语境的页面再把项目名接成第三段。
          // 早先的写法在 media/editor/ai 无项目时只显示"还没有项目",页面身份被抹掉
          // (三个项目页面看起来一模一样),这里修正。页面名是本页唯一的 h1。
          // 查不到就空着,**不兜成「首页」** —— 那正是 #/admin 顶着别人名字的原因。
          const labelKey = navLabelKey(view);
          const pageLabel = labelKey ? t(labelKey) : "";
          const scoped = PROJECT_SCOPED_VIEWS.includes(view);
          return (
            <div className="flex min-w-0 items-center gap-[7px] text-[13px] text-muted-foreground">
              <WorkspaceSwitcher
                workspaceId={workspaceId}
                workspaceName={workspaceName}
                workspaces={workspaces}
                onSelectWorkspace={onSelectWorkspace}
              />
              <span className="text-border-strong">/</span>
              <h1 className={cn("m-0 shrink-0 text-[13px] font-semibold text-foreground", scoped && "font-medium text-muted-foreground")}>{pageLabel}</h1>
              {scoped && (
                <>
                  <span className="text-border-strong">/</span>
                  {projectName ? (
                    onSwitchProject && projects.length > 0 ? (
                      <ProjectSwitcher
                        projects={projects}
                        currentProjectId={currentProjectId ?? null}
                        onSwitchProject={onSwitchProject}
                        onCreateProject={onCreateProject}
                        creatingProject={creatingProject}
                      />
                    ) : (
                      <strong className="truncate font-semibold text-foreground">{projectName}</strong>
                    )
                  ) : (
                    <span className="italic text-muted-foreground">{t("crumbNoProject")}</span>
                  )}
                </>
              )}
            </div>
          );
        })()}
        <div className="flex items-center gap-1">
          {actions}
          <button
            type="button"
            className="inline-flex h-[26px] cursor-pointer items-center gap-1.5 rounded-md border border-border bg-transparent px-[9px] text-xs text-muted-foreground transition-[border-color,color] duration-100 hover:border-border-strong hover:text-foreground max-[760px]:[&_kbd]:hidden max-[760px]:[&_span]:hidden [&_kbd]:rounded-sm [&_kbd]:border [&_kbd]:border-border [&_kbd]:px-1 [&_kbd]:text-[10px] [&_kbd]:leading-[15px] [&_kbd]:text-muted-foreground [&_kbd]:[font-family:inherit]"
            onClick={() => window.dispatchEvent(new CustomEvent("openstudio:open-cmdk"))}
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
      <aside className="col-start-1 row-start-2 flex flex-col items-center gap-0.5 border-r border-border bg-panel px-0 py-2 supports-[backdrop-filter]:bg-[var(--glass-chrome)] supports-[backdrop-filter]:[-webkit-backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] supports-[backdrop-filter]:[[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] [.is-desktop_&]:[-webkit-app-region:drag] [.is-desktop_&_:is(button,a)]:[-webkit-app-region:no-drag]">
        <div className="mb-2.5 grid h-[30px] w-[30px] select-none place-items-center rounded-md bg-primary text-[15px] font-bold text-primary-foreground" aria-hidden>
          <BrandMark size={22} />
        </div>
        {PRIMARY_NAV.map((item) => (
          <RailButton
            key={item.view}
            label={t(item.labelKey)}
            active={view === item.view}
            onClick={() => onViewChange(item.view)}
          >
            {ICONS[item.view]}
          </RailButton>
        ))}
        <div className="my-2 h-px w-6 bg-border" />
        {[...SECONDARY_NAV, ...(isDeploymentAdmin ? ADMIN_NAV : [])].map((item) => (
          <RailButton
            key={item.view}
            label={t(item.labelKey)}
            active={view === item.view}
            onClick={() => onViewChange(item.view)}
          >
            {ICONS[item.view]}
          </RailButton>
        ))}
        <div className="flex-1" />
        <RailUserMenu onOpenSettings={() => onViewChange("settings")} />
      </aside>
      <main className="col-start-2 row-start-2 h-full min-h-0 min-w-0 overflow-hidden bg-background supports-[backdrop-filter]:[[data-appearance=glass]_&]:m-2 supports-[backdrop-filter]:[[data-appearance=glass]_&]:h-auto supports-[backdrop-filter]:[[data-appearance=glass]_&]:rounded-xl supports-[backdrop-filter]:[[data-appearance=glass]_&]:border supports-[backdrop-filter]:[[data-appearance=glass]_&]:border-border supports-[backdrop-filter]:[[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.3)] supports-[backdrop-filter]:[[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.3)]">{children}</main>
    </div>
  );
}

/** In-editor timeline switcher: the project name in the breadcrumb becomes a dropdown of the
    workspace's projects (each = a timeline), so you can jump between timelines without going home.
    列表底部同样带「新建项目」入口 —— 理由和工作区切换器那条一样:不给可见线索,就没人
    知道这里能新建,只能绕回首页。 */
function ProjectSwitcher({
  projects,
  currentProjectId,
  onSwitchProject,
  onCreateProject,
  creatingProject,
}: {
  projects: { id: string; name: string }[];
  currentProjectId: string | null;
  onSwitchProject: (id: string) => void;
  onCreateProject?: () => void;
  creatingProject?: boolean;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const current = projects.find((p) => p.id === currentProjectId);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="-mx-1 inline-flex min-w-0 shrink cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-1 py-[3px] font-semibold text-foreground transition-colors duration-100 [font:inherit] hover:bg-secondary [&_svg]:text-muted-foreground"
          aria-label={t("timelineSwitch")}
        >
          <span className="truncate">{current?.name ?? ""}</span>
          <ChevronsUpDown size={12} className="shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="grid max-h-[min(60vh,360px)] w-64 gap-0.5 overflow-auto p-1.5" align="start" sideOffset={8}>
        <div className="px-2 pb-1.5 pt-1 text-[11px] font-semibold tracking-[0.02em] text-muted-foreground">{t("timelineSwitch")}</div>
        {projects.map((p) => (
          <button
            key={p.id}
            type="button"
            className={cn(
              "flex cursor-pointer items-center justify-between gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-[12.5px] text-foreground transition-colors duration-100 hover:bg-secondary [&_svg]:shrink-0 [&_svg]:text-primary",
              p.id === currentProjectId && "font-semibold text-primary",
            )}
            onClick={() => {
              setOpen(false);
              if (p.id !== currentProjectId) onSwitchProject(p.id);
            }}
          >
            <span className="truncate">{p.name}</span>
            {p.id === currentProjectId && <Check size={13} />}
          </button>
        ))}
        {onCreateProject && (
          <>
            <div className="mx-0.5 my-1 h-px bg-border" />
            <button
              type="button"
              disabled={creatingProject}
              className="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-[12.5px] text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground disabled:pointer-events-none disabled:opacity-60 [&_svg]:shrink-0"
              onClick={() => {
                setOpen(false);
                onCreateProject();
              }}
            >
              <FolderPlus size={13} />
              {t("createProject")}
            </button>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

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
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const createMut = useMutation({
    mutationFn: createWorkspace,
    onSuccess: (created) => {
      // 先把新工作区塞进缓存再选中:否则选中时列表里还没有它,
      // WorkspaceGate 的兜底(找不到 → 退回 list[0])会把选择弹回去。
      qc.setQueryData<Workspace[]>(["workspaces"], (old) => (old ? [created, ...old] : [created]));
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("workspaceCreated").replace("{name}", created.name));
      onSelectWorkspace?.(created.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (!onSelectWorkspace) {
    return <span className="shrink-0">{displayWorkspaceName(workspaceName, t)}</span>;
  }

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button type="button" className="-mx-1 inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-1 py-[3px] text-inherit transition-colors duration-100 [font:inherit] hover:bg-secondary hover:text-foreground [&_svg]:text-muted-foreground" aria-label={t("workspaceSwitch")}>
            {displayWorkspaceName(workspaceName, t)}
            <ChevronsUpDown size={12} />
          </button>
        </PopoverTrigger>
        <PopoverContent className="grid w-60 gap-0.5 p-1.5" align="start" sideOffset={8}>
          <div className="px-2 pb-1.5 pt-1 text-[11px] font-semibold tracking-[0.02em] text-muted-foreground">{t("workspaceSwitch")}</div>
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              type="button"
              className={cn(
              "flex cursor-pointer items-center justify-between gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-[12.5px] text-foreground transition-colors duration-100 hover:bg-secondary [&_svg]:shrink-0 [&_svg]:text-primary",
              ws.id === workspaceId && "font-semibold text-primary",
            )}
              onClick={() => {
                setOpen(false);
                if (ws.id !== workspaceId) onSelectWorkspace(ws.id);
              }}
            >
              <span className="truncate">{displayWorkspaceName(ws.name, t)}</span>
              {ws.id === workspaceId && <Check size={13} />}
            </button>
          ))}
          <div className="mx-0.5 my-1 h-px bg-border" />
          <button
            type="button"
            className="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-[12.5px] text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground [&_svg]:shrink-0"
            onClick={() => {
              setOpen(false);
              setCreating(true);
            }}
          >
            <FolderPlus size={13} />
            {t("workspaceNew")}
          </button>
        </PopoverContent>
      </Popover>
      <RenameDialog
        open={creating}
        title={t("workspaceNew")}
        initialValue=""
        onCancel={() => setCreating(false)}
        onSubmit={(name) => {
          setCreating(false);
          createMut.mutate(name);
        }}
      />
    </>
  );
}

/** 侧栏底部的用户入口:头像(用户名首字)→ 账号菜单 + 版本号。 */
function RailUserMenu({ onOpenSettings }: { onOpenSettings: () => void }) {
  const t = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const displayName = user?.display_name || user?.username || "user";
  const initial = displayName.slice(0, 1).toUpperCase();
  const avatarSrc = user?.avatar_key && user.id ? userAvatarUrl(user.id, user.avatar_key) : "";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="mx-auto mb-2.5 mt-1.5 grid h-[34px] w-[34px] cursor-pointer place-items-center overflow-hidden rounded-full border border-border bg-secondary text-[13px] font-bold text-foreground transition-[border-color] duration-100 hover:border-primary" aria-label={displayName}>
          {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
        </button>
      </PopoverTrigger>
      <PopoverContent className="grid w-[220px] gap-1.5 p-2" side="right" align="end" sideOffset={10}>
        <div className="flex items-center gap-2 px-1 py-0.5">
          <span className="grid h-8 w-8 place-items-center overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-[13px] font-bold text-primary">
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
          </span>
          <div className="grid [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:text-[13px]">
            <strong>{displayName}</strong>
            <small>{user?.username ? `@${user.username} · ${t("railLocalAccount")}` : t("railLocalAccount")}</small>
          </div>
        </div>
        <div className="grid gap-0.5 border-t border-border pt-2 [&_button]:flex [&_button]:cursor-pointer [&_button]:items-center [&_button]:gap-1.5 [&_button]:rounded [&_button]:border-0 [&_button]:bg-transparent [&_button]:px-1.5 [&_button]:py-[7px] [&_button]:text-left [&_button]:text-[12.5px] [&_button]:text-foreground [&_button]:transition-colors [&_button]:duration-100 [&_button:hover]:bg-secondary">
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
            className="text-destructive! hover:bg-[color-mix(in_oklab,var(--destructive)_8%,transparent)]!"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
          >
            <LogOut size={13} /> {t("signOut")}
          </button>
        </div>
        <div className="border-t border-border pt-2 text-center text-[10.5px] tabular-nums text-muted-foreground">Open Studio v{__APP_VERSION__}</div>
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
          className={cn(
          "relative grid h-9 w-9 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[background-color,color] duration-100 hover:bg-secondary hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
          active &&
            "bg-accent text-accent-foreground before:absolute before:-left-2.5 before:bottom-[9px] before:top-[9px] before:w-[2.5px] before:rounded-full before:bg-primary before:content-[''] hover:bg-accent hover:text-accent-foreground",
        )}
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
