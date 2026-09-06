import React from "react";
import {
  useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChartNoAxesCombined,
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
  Pencil,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Rocket,
  Scissors,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Trash2,
  Workflow, LayoutGrid } from "lucide-react";
import { toast } from "sonner";

import { api, createWorkspace, deleteWorkspace, renameWorkspace, userAvatarUrl, type Workspace } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { NotificationCenter } from "@/components/layout/NotificationCenter";
import { TaskCenter } from "@/components/layout/TaskCenter";
import { workspaceMenuState } from "@/components/layout/workspaceMenu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { MessageKey } from "@/app/messages";
import { NAV_ITEMS, navLabelKey, type StudioView } from "@/components/layout/navLabels";
import { cn } from "@/lib/utils";
import { WINDOW_CHROME_HEIGHT, WINDOW_CHROME_INSET } from "@/lib/windowChrome";

export type { StudioView } from "@/components/layout/navLabels";

/** 图标是**侧栏**的事(面包屑不画图标),所以只有它留在这里;
    「哪些页面、各叫什么」在 navLabels 那一份里。 */
const ICONS: Record<StudioView, React.ReactNode> = {
  home: <Home size={17} />,
  statistics: <ChartNoAxesCombined size={17} />,
  media: <FolderOpen size={17} />,
  editor: <Scissors size={17} />,
  ai: <Bot size={17} />,
  publish: <Rocket size={17} />,
  settings: <Settings size={17} />,
  workflows: <Workflow size={17} />,
  boards: <LayoutGrid size={17} />,
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
  const [narrow, setNarrow] = React.useState(() => window.matchMedia("(max-width: 1199px)").matches);
  const [collapsed, setCollapsed] = React.useState<boolean | null>(() => {
    try {
      const saved = localStorage.getItem("mosael.sidebar.collapsed");
      return saved === null ? null : saved === "true";
    } catch { return null; }
  });
  const compact = collapsed ?? narrow;
  React.useEffect(() => {
    const media = window.matchMedia("(max-width: 1199px)");
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const toggleSidebar = () => {
    setCollapsed(!compact);
    try { localStorage.setItem("mosael.sidebar.collapsed", String(!compact)); } catch { /* memory only */ }
  };

  // 桌面端启动静默更新检查的回报:有新版弹一条可点开发布页的提示(不打断)。
  React.useEffect(() => {
    return window.mosaelDesktop?.onUpdateAvailable?.((info) => {
      if (!info?.hasUpdate) return;
      toast(t("updateAvailable").replace("{version}", info.latest ?? ""), {
        duration: 12000,
        action: { label: t("updateView"), onClick: () => window.open(info.url, "_blank") },
      });
    });
  }, [t]);

  return (
    <div data-studio-shell data-sidebar-collapsed={compact} className="grid h-screen grid-cols-[var(--studio-sidebar)_minmax(0,1fr)] grid-rows-[var(--window-chrome-height)_minmax(0,1fr)]" style={{ "--window-chrome-height": `${WINDOW_CHROME_HEIGHT}px`, "--studio-sidebar": compact ? "64px" : "224px" } as React.CSSProperties}>
      <header
        data-glass-surface className={cn(
        "col-span-full flex min-w-0 items-center justify-between gap-4 border-b border-divider bg-panel px-4 [.is-desktop_&]:[-webkit-app-region:drag] [.is-desktop_&_:is(button,a,input,[role=button])]:[-webkit-app-region:no-drag]",
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
            <div className="flex min-w-0 items-center gap-3 text-ui-sm text-muted-foreground">
              <Button variant="ghost" size="icon" onClick={toggleSidebar} aria-expanded={!compact} aria-controls="studio-navigation" aria-label={compact ? t("navExpand") : t("navCollapse")}>
                {compact ? <PanelLeftOpen /> : <PanelLeftClose />}
              </Button>
              <h1 className={cn("m-0 shrink-0 text-ui-sm font-semibold text-foreground", scoped && "font-medium text-muted-foreground")}>{pageLabel}</h1>
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
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          <button
            type="button"
            aria-label={t("cmdkTitle")}
            className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-transparent px-[9px] text-xs text-muted-foreground transition-[border-color,color] duration-100 hover:border-border-strong hover:text-foreground max-[760px]:[&_kbd]:hidden max-[760px]:[&_span]:hidden [&_kbd]:rounded-sm [&_kbd]:border [&_kbd]:border-border [&_kbd]:px-1 [&_kbd]:text-ui-2xs [&_kbd]:leading-[15px] [&_kbd]:text-muted-foreground [&_kbd]:[font-family:inherit]"
            onClick={() => window.dispatchEvent(new CustomEvent("mosael:open-cmdk"))}
          >
            <Search size={15} />
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
      <aside data-glass-surface className="col-start-1 row-start-2 flex min-h-0 flex-col border-r border-divider bg-panel px-3 py-3">
        <div className="mb-4 shrink-0">
          <WorkspaceSwitcher compact={compact} workspaceId={workspaceId} workspaceName={workspaceName} workspaces={workspaces} onSelectWorkspace={onSelectWorkspace} />
        </div>
        <nav id="studio-navigation" aria-label={t("navMain")} className="flex min-h-0 flex-1 flex-col gap-1 [@media(max-height:850px)]:gap-0.5 overflow-y-auto overflow-x-hidden">
          {PRIMARY_NAV.filter((item) => item.view !== "settings").map((item) => (
            <RailButton key={item.view} compact={compact} label={t(item.labelKey)} active={view === item.view} onClick={() => onViewChange(item.view)}>
              {ICONS[item.view]}
            </RailButton>
          ))}
          <div className="mx-2 my-3 [@media(max-height:850px)]:my-2 border-t border-divider" />
          {[...SECONDARY_NAV, ...(isDeploymentAdmin ? ADMIN_NAV : [])].map((item) => (
            <RailButton key={item.view} compact={compact} label={t(item.labelKey)} active={view === item.view} onClick={() => onViewChange(item.view)}>
              {ICONS[item.view]}
            </RailButton>
          ))}
        </nav>
        <div className="mt-3 grid shrink-0 gap-1 border-t border-divider pt-3">
          <RailButton compact={compact} label={t("navSettings")} active={view === "settings"} onClick={() => onViewChange("settings")}>
            {ICONS.settings}
          </RailButton>
          <RailUserMenu compact={compact} onOpenSettings={() => onViewChange("settings")} />
        </div>
      </aside>
      {/* data-glass-surface:开了自定义背景时由 tokens.css 统一给模糊 —— 几何一个字都不改。
          此前这里在 glass 下会长出 m-2/h-auto/rounded-xl/border,内容区于是从铺满变成浮起的卡。 */}
      <main data-glass-surface className="col-start-2 row-start-2 h-full min-h-0 min-w-0 overflow-hidden bg-background">
        {children}
      </main>
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
        <div className="px-2 pb-1.5 pt-1 text-ui-xs font-semibold tracking-[0.02em] text-muted-foreground">{t("timelineSwitch")}</div>
        {projects.map((p) => (
          <button
            key={p.id}
            type="button"
            className={cn(
              "flex cursor-pointer items-center justify-between gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-ui-sm text-foreground transition-colors duration-100 hover:bg-secondary [&_svg]:shrink-0 [&_svg]:text-primary",
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
              className="flex cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-ui-sm text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground disabled:pointer-events-none disabled:opacity-60 [&_svg]:shrink-0"
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
  compact,
  workspaceId,
  workspaceName,
  workspaces,
  onSelectWorkspace,
}: {
  compact: boolean;
  workspaceId?: string;
  workspaceName: string;
  workspaces: Workspace[];
  onSelectWorkspace?: (id: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  // 右键菜单要操作的**不一定是当前工作区** —— 所以这两个 state 存的是那一行的对象,
  // 不是一个布尔开关。
  const [renaming, setRenaming] = React.useState<Workspace | null>(null);
  const [removing, setRemoving] = React.useState<Workspace | null>(null);

  const renameMut = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameWorkspace(id, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("saved"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => deleteWorkspace(id),
    onSuccess: (_data, id) => {
      // 删掉的正好是当前这个的话,先把选择挪到别处再让列表失效 —— 反过来的话,
      // 中间那一瞬列表里没有当前工作区,WorkspaceGate 会先弹一次。
      if (id === workspaceId) {
        const next = workspaces.find((ws) => ws.id !== id);
        if (next) onSelectWorkspace?.(next.id);
      }
      qc.setQueryData<Workspace[]>(["workspaces"], (old) => old?.filter((ws) => ws.id !== id));
      void qc.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("workspaceDeleted"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

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
    return <span className="block truncate px-2 text-ui-sm" title={workspaceName}>{compact ? workspaceName.slice(0, 1) : workspaceName}</span>;
  }

  return (
    <>
      <Popover open={open} onOpenChange={(next) => { setOpen(next); setSearch(""); }}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button type="button" className={cn("flex w-full min-w-0 cursor-pointer items-center rounded-lg text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", compact ? "aspect-square justify-center bg-accent p-0 text-primary hover:bg-primary/20 data-[state=open]:ring-2 data-[state=open]:ring-ring" : "h-14 gap-2.5 px-2 hover:bg-secondary data-[state=open]:bg-secondary")} aria-label={t("workspaceSwitch")} title={workspaceName}>
                <span className={cn("grid shrink-0 place-items-center text-primary", compact ? "size-5" : "size-8 rounded-md bg-accent")}><Boxes size={compact ? 20 : 18} /></span>
                {!compact && <><span className="min-w-0 flex-1"><span className="block truncate text-ui-sm font-semibold">{workspaceName}</span><span className="block text-ui-xs text-muted-foreground">{t("workspaceSwitch")}</span></span><ChevronsUpDown size={14} className="shrink-0 text-muted-foreground" /></>}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          {compact && <TooltipContent side="right">{workspaceName} · {t("workspaceSwitch")}</TooltipContent>}
        </Tooltip>
        <PopoverContent className="w-80 p-2" side={compact ? "right" : "bottom"} align="start" sideOffset={12}>
          <div className="flex items-center justify-between px-2 pb-3 pt-2"><span className="text-ui-md font-semibold">{t("workspaceSwitch")}</span><span className="text-ui-xs font-medium text-muted-foreground">Mosael</span></div>
          <Input aria-label={t("workspaceSearch")} placeholder={t("workspaceSearch")} value={search} onChange={(e) => setSearch(e.target.value)} className="mb-2" />
          <div className="max-h-72 overflow-y-auto">
          {workspaces.filter(ws => ws.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())).map((ws) => {
            const gate = workspaceMenuState(ws.role, workspaces.length);
            return (
              <ContextMenu key={ws.id}>
                <ContextMenuTrigger asChild>
                  <div className={cn("flex items-center gap-1 rounded-md p-1 hover:bg-secondary", ws.id === workspaceId && "bg-accent")}>
                    <button type="button" className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-left text-ui-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => { setOpen(false); setSearch(""); if (ws.id !== workspaceId) onSelectWorkspace(ws.id); }} aria-current={ws.id === workspaceId ? "true" : undefined}>
                      <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-panel text-primary">{ws.name.slice(0, 1)}</span>
                      <span className="truncate">{ws.name}</span>
                      {ws.id === workspaceId && <Check size={14} className="ml-auto shrink-0 text-primary" />}
                    </button>
                    <Button variant="ghost" size="icon-xs" disabled={gate.renameDisabled} aria-label={`${t("rename")}: ${ws.name}`} title={t("rename")} onClick={() => { setOpen(false); setRenaming(ws); }}><Pencil /></Button>
                    <Button variant="ghost" size="icon-xs" disabled={gate.deleteDisabled} aria-label={`${t("delete")}: ${ws.name}`} title={t("delete")} className="text-destructive hover:text-destructive" onClick={() => { setOpen(false); setRemoving(ws); }}><Trash2 /></Button>
                  </div>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem disabled={gate.renameDisabled} onSelect={() => { setOpen(false); setRenaming(ws); }}><Pencil /> {t("rename")}</ContextMenuItem>
                  <ContextMenuItem disabled={gate.deleteDisabled} className="text-destructive focus:text-destructive" onSelect={() => { setOpen(false); setRemoving(ws); }}><Trash2 /> {t("delete")}</ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            );
          })}
          {workspaces.every(ws => !ws.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) && <p className="px-2 py-4 text-ui-sm text-muted-foreground">{t("workspaceNoResults")}</p>}
          </div>
          <div className="my-2 border-t border-divider" />
          <Button variant="ghost" className="w-full justify-start text-primary" onClick={() => { setOpen(false); setCreating(true); }}><FolderPlus />{t("workspaceNew")}</Button>
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
      <RenameDialog
        open={renaming !== null}
        title={t("renameWorkspace")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => {
          const target = renaming;
          setRenaming(null);
          if (target && name.trim() && name.trim() !== target.name) {
            renameMut.mutate({ id: target.id, name: name.trim() });
          }
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t("deleteWorkspace")}
        body={t("deleteWorkspaceConfirm").replace("{name}", removing?.name ?? "")}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing;
          setRemoving(null);
          if (target) removeMut.mutate(target.id);
        }}
      />
    </>
  );
}

/** 侧栏底部的用户入口:头像(用户名首字)→ 账号菜单 + 版本号。 */
function RailUserMenu({ compact, onOpenSettings }: { compact: boolean; onOpenSettings: () => void }) {
  const t = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const displayName = user?.display_name || user?.username || "user";
  const initial = displayName.slice(0, 1).toUpperCase();
  const avatarSrc = user?.avatar_key && user.id ? userAvatarUrl(user.id, user.avatar_key) : "";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className={cn("flex h-11 w-full cursor-pointer items-center gap-2.5 rounded-md px-2 text-left hover:bg-secondary", compact && "justify-center px-0")} aria-label={displayName}>
          <span className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-full bg-secondary text-sm font-semibold">
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
          </span>
          {!compact && <><span className="min-w-0 flex-1 truncate text-ui-sm font-medium">{displayName}</span><ChevronsUpDown size={14} className="shrink-0 text-muted-foreground" /></>}
        </button>
      </PopoverTrigger>
      <PopoverContent className="grid w-[220px] gap-1.5 p-2" side="right" align="end" sideOffset={10}>
        <div className="flex items-center gap-2 px-1 py-0.5">
          <span className="grid h-8 w-8 place-items-center overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-ui-md font-bold text-primary">
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
          </span>
          <div className="grid [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:text-ui-md">
            <strong>{displayName}</strong>
            <small>{user?.username ? `@${user.username} · ${t("railLocalAccount")}` : t("railLocalAccount")}</small>
          </div>
        </div>
        <div className="grid gap-0.5 border-t border-divider pt-2 [&_button]:flex [&_button]:cursor-pointer [&_button]:items-center [&_button]:gap-1.5 [&_button]:rounded [&_button]:border-0 [&_button]:bg-transparent [&_button]:px-1.5 [&_button]:py-[7px] [&_button]:text-left [&_button]:text-ui-sm [&_button]:text-foreground [&_button]:transition-colors [&_button]:duration-100 [&_button:hover]:bg-secondary">
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
        <div className="border-t border-divider pt-2 text-center text-ui-2xs tabular-nums text-muted-foreground">Mosael v{__APP_VERSION__}</div>
      </PopoverContent>
    </Popover>
  );
}

function RailButton({
  compact,
  label,
  active,
  onClick,
  children,
}: {
  compact: boolean;
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
          "relative flex h-10 [@media(max-height:850px)]:h-9 w-full shrink-0 cursor-pointer items-center gap-3 rounded-md border-0 bg-transparent px-3 text-left text-ui-sm font-medium text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring [&>svg]:shrink-0",
          compact && "justify-center px-0",
          active &&
            "bg-accent font-semibold text-accent-foreground hover:bg-accent hover:text-accent-foreground",
        )}
          onClick={onClick}
          aria-label={label}
          aria-current={active ? "page" : undefined}
        >
          {children}
          {!compact && <span className="truncate">{label}</span>}
        </button>
      </TooltipTrigger>
      {compact && <TooltipContent side="right">{label}</TooltipContent>}
    </Tooltip>
  );
}
