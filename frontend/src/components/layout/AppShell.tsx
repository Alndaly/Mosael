import React from "react";
import {
  Boxes,
  Check,
  ChevronsUpDown,
  FolderPlus,
  Languages,
  LogOut,
  Pencil,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Trash2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { customServerHost, userAvatarUrl, type Workspace } from "@/api/client";
import { useAuth, useIsDeploymentAdmin } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { NotificationCenter } from "@/components/jobs/NotificationCenter";
import { TaskCenter } from "@/components/jobs/TaskCenter";
import {
  workspaceDeleteBlockedReason,
  workspaceMenuState,
  workspaceRenameBlockedReason,
} from "@/components/layout/workspaceMenu";
import { THEME_ICONS, THEME_LABEL_KEYS, nextTheme } from "@/components/layout/themeCycle";
import { accountOrigin } from "@/components/layout/accountOrigin";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { navItemsAt, navLabelKey, type NavItem, type StudioView } from "@/components/layout/navLabels";
import { gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";
import { useCreateWorkspace, useDeleteWorkspace, useRenameWorkspace } from "@/lib/workspaces";
import { PageTrailProvider, type PageTrail } from "@/components/layout/pageTrail";
import { WINDOW_CHROME_HEIGHT, WINDOW_CHROME_INSET } from "@/lib/windowChrome";

export type { StudioView } from "@/components/layout/navLabels";

/** 侧栏的几组,从那一份页面声明里按 placement 取 —— 侧栏不再自己记"哪些页在哪一组"。 */
const PRIMARY_NAV = navItemsAt("primary");
/** admin 那一格只对部署管理员显示。**藏起来的入口不是权限** —— 后端每条 /api/admin 路由
 *  各自把关,这里只是不给不相干的人添乱。 */
const SECONDARY_NAV = navItemsAt("secondary");
const ADMIN_NAV = navItemsAt("admin");
const FOOTER_NAV = navItemsAt("footer");

/** 只有「剪辑」工作在"当前项目"语境 —— 它编辑的就是某个项目的时间线。
    其余页面的面包屑显示页面名,否则设置/插件页也挂着项目名,既不合理也容易误解。
    「素材」是**工作区级**资源池(素材属于工作区,project_id 可空且删项目只置空)。
    「AI 助手」同理是工作区级:智能体本身就能跨项目管理(列项目、改时间线都是它的工具),
    把会话锁在"当前项目"是把关系搞反了 —— 它是项目的操作者,不是项目的附属物。 */
const PROJECT_SCOPED_VIEWS: StudioView[] = ["editor"];

//: 路径里点得回去的那几段:看着是字,悬停才像链接 —— 顶栏不是一排按钮。
const TRAIL_LINK =
  "cursor-pointer rounded-sm border-0 bg-transparent p-0 text-inherit transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

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
  const ThemeIcon = THEME_ICONS[theme];
  const isDeploymentAdmin = useIsDeploymentAdmin();
  const [narrow, setNarrow] = React.useState(() => window.matchMedia("(max-width: 1199px)").matches);
  const [collapsed, setCollapsed] = React.useState<boolean | null>(() => {
    try {
      const saved = localStorage.getItem("mosael.sidebar.collapsed");
      return saved === null ? null : saved === "true";
    } catch { return null; }
  });
  const compact = collapsed ?? narrow;
  //: 子页面交上来的路径下半截(见 pageTrail)。换了页面就清掉 —— 上一页的「小美 / 中年」不该挂到下一页上。
  //: **在渲染时比,不用 effect**:子页面的 effect 先于这里的跑,放在 effect 里清会把子页面刚交上来的那条又抹掉。
  const [trail, setTrail] = React.useState<PageTrail | null>(null);
  const [trailView, setTrailView] = React.useState(view);
  if (trailView !== view) {
    setTrailView(view);
    setTrail(null);
  }
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

  const railItem = (item: NavItem) => {
    const Icon = item.icon;
    return (
      <RailButton key={item.view} compact={compact} label={t(item.labelKey)} active={view === item.view} onClick={() => onViewChange(item.view)}>
        <Icon size={17} />
      </RailButton>
    );
  };

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
              <h1 className={cn("m-0 shrink-0 text-ui-sm font-semibold text-foreground", (scoped || trail) && "font-medium text-muted-foreground")}>
                {trail?.onRoot ? (
                  <button type="button" onClick={trail.onRoot} className={TRAIL_LINK}>
                    {pageLabel}
                  </button>
                ) : (
                  pageLabel
                )}
              </h1>
              {trail?.segments.map((segment, index) => {
                const last = index === trail.segments.length - 1;
                return (
                  <React.Fragment key={`${index}:${segment.label}`}>
                    <span className="text-border-strong">/</span>
                    {last && segment.onRename ? (
                      <button
                        type="button"
                        onClick={segment.onRename}
                        aria-current="page"
                        aria-label={`${segment.label} · ${segment.renameLabel ?? ""}`}
                        title={`${segment.label} · ${segment.renameLabel ?? ""}`}
                        className="group/rename inline-flex max-w-64 cursor-pointer items-center gap-1 rounded-sm border-0 bg-transparent p-0 font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="truncate">{segment.label}</span>
                        <Pencil size={11} className="shrink-0 opacity-0 transition-opacity group-hover/rename:opacity-60" aria-hidden />
                      </button>
                    ) : segment.onSelect && !last ? (
                      <button type="button" onClick={segment.onSelect} className={cn(TRAIL_LINK, "max-w-48 truncate")} title={segment.label}>
                        {segment.label}
                      </button>
                    ) : (
                      <span
                        className={cn("max-w-64 truncate", last ? "font-semibold text-foreground" : "")}
                        aria-current={last ? "page" : undefined}
                        title={segment.label}
                      >
                        {segment.label}
                      </span>
                    )}
                  </React.Fragment>
                );
              })}
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
            className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-transparent px-[9px] text-xs text-muted-foreground transition-[border-color,color] duration-100 hover:border-border-strong hover:text-foreground max-[760px]:[&_span]:hidden"
            onClick={() => window.dispatchEvent(new CustomEvent("mosael:open-cmdk"))}
          >
            <Search size={15} />
            <span>{t("cmdkTitle")}</span>
            <Kbd className="max-[760px]:hidden">⌘K</Kbd>
          </button>
          {workspaceId && <TaskCenter workspaceId={workspaceId} />}
          {workspaceId && <NotificationCenter workspaceId={workspaceId} />}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setTheme(nextTheme(theme))}
                aria-label={t("settingsTheme")}
              >
                <ThemeIcon size={15} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {t(THEME_LABEL_KEYS[theme])}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")}
                aria-label={locale === "zh-CN" ? t("languageSwitchToEn") : t("languageSwitchToZh")}
              >
                <Languages size={15} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{locale === "zh-CN" ? t("languageEn") : t("languageZh")}</TooltipContent>
          </Tooltip>
        </div>
      </header>
      <aside data-glass-surface className="col-start-1 row-start-2 flex min-h-0 flex-col border-r border-divider bg-panel px-3 py-3">
        <div className="mb-4 shrink-0">
          <WorkspaceSwitcher compact={compact} workspaceId={workspaceId} workspaceName={workspaceName} workspaces={workspaces} onSelectWorkspace={onSelectWorkspace} />
        </div>
        <nav id="studio-navigation" aria-label={t("navMain")} className="flex min-h-0 flex-1 flex-col gap-1 [@media(max-height:850px)]:gap-0.5 overflow-y-auto overflow-x-hidden">
          {PRIMARY_NAV.map(railItem)}
          <div className="mx-2 my-3 [@media(max-height:850px)]:my-2 border-t border-divider" />
          {[...SECONDARY_NAV, ...(isDeploymentAdmin ? ADMIN_NAV : [])].map(railItem)}
        </nav>
        <div className="mt-3 grid shrink-0 gap-1 border-t border-divider pt-3">
          {FOOTER_NAV.map(railItem)}
          <RailUserMenu compact={compact} />
        </div>
      </aside>
      {/* data-glass-surface:开了自定义背景时由 tokens.css 统一给模糊 —— 几何一个字都不改。
          此前这里在 glass 下会长出 m-2/h-auto/rounded-xl/border,内容区于是从铺满变成浮起的卡。 */}
      <main data-glass-surface className="col-start-2 row-start-2 h-full min-h-0 min-w-0 overflow-hidden bg-background">
        <PageTrailProvider value={setTrail}>{children}</PageTrailProvider>
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
      <PopoverContent className="grid max-h-[min(60vh,360px)] w-80 grid-cols-[minmax(0,1fr)] gap-0.5 overflow-x-hidden overflow-y-auto p-1.5" align="start" sideOffset={8}>
        <div className="px-2 pb-1.5 pt-1 text-ui-xs font-semibold tracking-[0.02em] text-muted-foreground">{t("timelineSwitch")}</div>
        {projects.map((p) => (
          <button
            key={p.id}
            type="button"
            className={cn(
              "flex min-w-0 w-full cursor-pointer items-center justify-between gap-2 rounded-md border-0 bg-transparent px-2 py-[7px] text-left text-ui-sm text-foreground transition-colors duration-100 hover:bg-secondary [&_svg]:shrink-0 [&_svg]:text-primary",
              p.id === currentProjectId && "font-semibold text-primary",
            )}
            onClick={() => {
              setOpen(false);
              if (p.id !== currentProjectId) onSwitchProject(p.id);
            }}
          >
            <span className="min-w-0 flex-1 truncate" title={p.name}>{p.name}</span>
            {p.id === currentProjectId && <Check size={13} />}
          </button>
        ))}
        {onCreateProject && (
          <>
            <div className="mx-0.5 my-1 h-px bg-divider" />
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
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  // 右键菜单要操作的**不一定是当前工作区** —— 所以这两个 state 存的是那一行的对象,
  // 不是一个布尔开关。
  const [renaming, setRenaming] = React.useState<Workspace | null>(null);
  const [removing, setRemoving] = React.useState<Workspace | null>(null);

  const renameMut = useRenameWorkspace({ onSettled: () => setRenaming(null) });
  const removeMut = useDeleteWorkspace({ onSettled: () => setRemoving(null) });
  const createMut = useCreateWorkspace({
    onCreated: (created) => {
      toast.success(t("workspaceCreated").replace("{name}", created.name));
      onSelectWorkspace?.(created.id);
    },
    onSettled: () => setCreating(false),
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
            //: 灰掉的按钮要说为什么 —— 权限不够和「只剩这一个」是两件事,用户得知道该找谁、还是先建一个。
            const renameReason = workspaceRenameBlockedReason(gate);
            const deleteReason = workspaceDeleteBlockedReason(gate);
            return (
              <ContextMenu key={ws.id}>
                <ContextMenuTrigger asChild>
                  <div className={cn("flex items-center gap-1 rounded-md p-1 hover:bg-secondary", ws.id === workspaceId && "bg-accent")}>
                    <button type="button" className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-left text-ui-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => { setOpen(false); setSearch(""); if (ws.id !== workspaceId) onSelectWorkspace(ws.id); }} aria-current={ws.id === workspaceId ? "true" : undefined}>
                      <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-panel text-primary">{ws.name.slice(0, 1)}</span>
                      <span className="truncate">{ws.name}</span>
                      {ws.id === workspaceId && <Check size={14} className="ml-auto shrink-0 text-primary" />}
                    </button>
                    <Button variant="ghost" size="icon-xs" disabled={gate.renameDisabled} aria-label={`${t("rename")}: ${ws.name}`} title={renameReason ? t(renameReason) : t("rename")} onClick={() => { setOpen(false); setRenaming(ws); }}><Pencil /></Button>
                    <Button variant="ghost" size="icon-xs" disabled={gate.deleteDisabled} aria-label={`${t("delete")}: ${ws.name}`} title={deleteReason ? t(deleteReason) : t("delete")} className="text-destructive hover:text-destructive" onClick={() => { setOpen(false); setRemoving(ws); }}><Trash2 /></Button>
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
        pending={createMut.isPending}
        onSubmit={(name) => createMut.mutate(name)}
      />
      <RenameDialog
        open={renaming !== null}
        title={t("renameWorkspace")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        pending={renameMut.isPending}
        onSubmit={(name) => {
          if (!renaming) return;
          // 名字没变就不必等服务端,直接关。
          if (name.trim() === renaming.name) setRenaming(null);
          else renameMut.mutate({ id: renaming.id, name: name.trim() });
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t("deleteWorkspace")}
        body={t("deleteWorkspaceConfirm").replace("{name}", removing?.name ?? "")}
        onCancel={() => setRemoving(null)}
        pending={removeMut.isPending}
        onConfirm={() => {
          if (removing) removeMut.mutate(removing.id);
        }}
      />
    </>
  );
}

/** 侧栏底部的用户入口:头像(用户名首字)→ 账号菜单 + 版本号。 */
function RailUserMenu({ compact }: { compact: boolean }) {
  const t = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = React.useState(false);
  const displayName = user?.display_name || user?.username || "user";
  const initial = displayName.slice(0, 1).toUpperCase();
  const avatarSrc = user?.avatar_key && user.id ? userAvatarUrl(user.id, user.avatar_key) : "";
  const origin = accountOrigin(t, customServerHost(), user?.oauth_providers ?? []);

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
          <div className="grid min-w-0 [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:text-ui-md">
            <strong>{displayName}</strong>
            {user?.username && <small>@{user.username}</small>}
            <small>{origin}</small>
          </div>
        </div>
        <div className="grid gap-0.5 border-t border-divider pt-2 [&_button]:flex [&_button]:cursor-pointer [&_button]:items-center [&_button]:gap-1.5 [&_button]:rounded [&_button]:border-0 [&_button]:bg-transparent [&_button]:px-1.5 [&_button]:py-[7px] [&_button]:text-left [&_button]:text-ui-sm [&_button]:text-foreground [&_button]:transition-colors [&_button]:duration-100 [&_button:hover]:bg-secondary">
          {/* 直达「账号」那一节:侧栏底部已经有一个「设置」,而它回到的是上次停留的分区 ——
              从账号菜单点进去的人要的是账号本身。 */}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              gotoSettings("account");
            }}
          >
            <UserRound size={13} /> {t("railAccountSettings")}
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
