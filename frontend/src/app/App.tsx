import React from "react";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FolderPlus,
  Loader2,
  RotateCw,
  X,
} from "lucide-react";

import {
  api,
  importLocalAsset,
  type ProjectWithStats,
  type Workspace,
} from "@/api/client";
import { createMutationCache } from "@/app/mutationErrors";
import { AuthProvider, useAuth } from "@/app/auth";
import { AppearanceProvider } from "@/app/appearance";
import { CustomCssProvider } from "@/app/customCss";
import {
  PreferencesProvider,
  useI18n,
  usePreferences,
} from "@/app/preferences";
import { Toaster, toast } from "sonner";
import { LoginView } from "@/features/auth/LoginView";
import { AppShell, type StudioView } from "@/components/layout/AppShell";
import { BrandMark } from "@/components/layout/BrandMark";
import { STUDIO_VIEWS } from "@/components/layout/navLabels";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ConfirmationCenter } from "@/components/layout/ConfirmationCenter";
import { VoiceDock } from "@/components/agent/VoiceDock";
import { useAgentNavigation } from "@/components/agent/useAgentNavigation";
import { PlugZap } from "lucide-react";

import { ServerPicker } from "@/components/layout/ServerPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BrowserPreview } from "@/components/layout/BrowserPreview";
import { LivePanels } from "@/components/layout/LivePanels";
import { StartupLoading } from "@/components/layout/StartupLoading";
import { Input } from "@/components/ui/input";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { cn } from "@/lib/utils";
import { listenDesktopDeepLinks } from "@/lib/deepLink";
import { useCreateProject } from "@/lib/useCreateProject";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AiStudio } from "@/features/ai-studio/AiStudio";
import { EditorView } from "@/features/editor/EditorView";
import { HomeView } from "@/features/home/HomeView";
import { MediaLibraryView } from "@/features/media/MediaLibraryView";
import { RecordingProvider } from "@/features/media/RecordingProvider";
import { PublishView } from "@/features/publish/PublishView";
import { BrowserPoolView } from "@/features/browser-pool/BrowserPoolView";
import { PluginsView } from "@/features/plugins/PluginsView";
import { SchedulerView } from "@/features/scheduler/SchedulerView";
import { BoardsView } from "@/features/boards/BoardsView";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";
import { AdminView } from "@/features/admin/AdminView";
import { SettingsView } from "@/features/settings/SettingsView";

// 页面是条件挂载(切页整棵卸载/重挂),默认 staleTime:0 会让每次切页都重拉 → 首帧空态闪一下。
// 给个合理缓存窗口:短时间切回同页直接用缓存,不重拉不闪;需要实时的 query 各自设了 refetchInterval,
// 不受影响。获焦不全量重拉(Electron 频繁获焦会加剧闪烁)。

const queryClient = new QueryClient({
  mutationCache: createMutationCache((message) => toast.error(message)),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <AppearanceProvider>
          {/* 自定义 CSS 包在外观里面:它压过应用自带的一切样式,自然也压过外观那几个令牌。 */}
          <CustomCssProvider>
            <TooltipProvider delayDuration={300}>
              <AuthProvider>
                <ImagePreviewProvider>
                  <AuthGate />
                  <AppToaster />
                  <PublishViewBar />
                  <BrowserPreview />
                  <LivePanels />
                </ImagePreviewProvider>
              </AuthProvider>
            </TooltipProvider>
          </CustomCssProvider>
        </AppearanceProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  );
}

/** 这条工具栏的高度。**内嵌发布视图正是从这个像素处开始铺**(Electron 侧的
 *  EMBED_HEADER_HEIGHT),两者不等就会露出一条缝、缝里是 App 自己的顶栏。
 *  由 contracts/shared-constants.json 钉住。 */
export const PUBLISH_BAR_HEIGHT = 48;

/** Electron 内嵌发布视图可见时的顶部浏览器工具栏:后退/前进/刷新 + 地址栏 + 返回 Mosael。
 *  条底可拖窗(-webkit-app-region: drag),控件各自 no-drag。 */
function PublishViewBar() {
  const t = useI18n();
  const [state, setState] = React.useState<PublishViewState>({
    visible: false,
    accountId: null,
    accountName: null,
  });
  const [address, setAddress] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  React.useEffect(
    () => window.mosaelPublish?.onViewState((next) => setState(next)),
    [],
  );
  // 地址随导航更新,但用户正在输入时不覆盖(否则打字被主进程回报打断)。
  React.useEffect(() => {
    if (!editing) setAddress(state.url ?? "");
  }, [state.url, editing]);
  if (!state.visible) return null;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = address.trim();
    if (value) void window.mosaelPublish?.navigate(value);
    (
      event.currentTarget.querySelector("input") as HTMLInputElement | null
    )?.blur();
  };

  return (
    <div
      style={{ height: PUBLISH_BAR_HEIGHT }}
      className={cn(
        "fixed inset-x-0 top-0 z-[200] flex items-center gap-2 border-b border-border-strong bg-panel px-2.5 [-webkit-app-region:drag] supports-[backdrop-filter]:bg-[var(--glass-chrome)] supports-[backdrop-filter]:[-webkit-backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[backdrop-filter:blur(14px)_saturate(1.4)]",
        WINDOW_CHROME_INSET,
      )}
    >
      <div className="[-webkit-app-region:no-drag] inline-flex items-center gap-0.5">
        <button
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          disabled={!state.canGoBack}
          onClick={() => void window.mosaelPublish?.back()}
          title={t("navBack")}
          aria-label={t("navBack")}
        >
          <ChevronLeft size={16} />
        </button>
        <button
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          disabled={!state.canGoForward}
          onClick={() => void window.mosaelPublish?.forward()}
          title={t("navForward")}
          aria-label={t("navForward")}
        >
          <ChevronRight size={16} />
        </button>
        <button
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          onClick={() => void window.mosaelPublish?.reload()}
          title={state.loading ? t("navStop") : t("navReload")}
          aria-label={state.loading ? t("navStop") : t("navReload")}
        >
          {state.loading ? <X size={15} /> : <RotateCw size={14} />}
        </button>
      </div>
      <form
        className="[-webkit-app-region:no-drag] flex h-[30px] min-w-0 flex-1 items-center gap-1.5 rounded-lg border border-border bg-panel-inset px-2.5 focus-within:border-ring [&_input]:min-w-0 [&_input]:flex-1 [&_input]:border-0 [&_input]:bg-transparent [&_input]:text-ui-sm [&_input]:text-foreground [&_input]:outline-none [&_input:focus-visible]:ring-0"
        onSubmit={submit}
      >
        {state.loading && (
          <Loader2
            size={13}
            className="flex-none animate-mosael-spin text-muted-foreground"
          />
        )}
        <Input
          value={address}
          spellCheck={false}
          placeholder={t("addressPlaceholder")}
          onChange={(event) => setAddress(event.target.value)}
          onFocus={(event) => {
            setEditing(true);
            event.target.select();
          }}
          onBlur={() => {
            setEditing(false);
            setAddress(state.url ?? "");
          }}
        />
      </form>
      <button
        type="button"
        className="[-webkit-app-region:no-drag] inline-flex cursor-pointer items-center gap-[5px] whitespace-nowrap rounded-md border border-border bg-transparent px-2.5 py-[5px] text-ui-sm text-foreground hover:border-border-strong hover:bg-secondary"
        onClick={() => void window.mosaelPublish?.hideView()}
      >
        <ArrowLeft size={14} /> {t("publishBackToApp")}
      </button>
    </div>
  );
}

/** Sonner 跟随应用主题;样式对齐全平面(细边框、无投影由 CSS 覆盖)。 */
function AppToaster() {
  const { theme } = usePreferences();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      gap={8}
      toastOptions={{
        className:
          "rounded-lg! border! border-border-strong! bg-popover! text-ui-sm! text-foreground! shadow-none!",
      }}
    />
  );
}

/**
 * 登录/建工作区之前的全屏过渡页(连接中、选工作区…)。这些页面不挂 AppShell,而无边框窗口
 * 的拖拽区一向由 AppShell 顶栏提供 —— 少了它,窗口在这些状态下**完全拖不动**(启动连接
 * 可能要好几秒)。这里统一补一条顶部透明拖拽带,内部交互元素标 no-drag。
 */
function PreShellScreen({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center text-muted-foreground">
      <div
        className="fixed inset-x-0 top-0 z-[5] hidden h-11 [.is-desktop_&]:block [-webkit-app-region:drag]"
        aria-hidden
      />
      <div className="[&_:is(button,a,input,[role=button])]:[-webkit-app-region:no-drag]">
        {children}
      </div>
    </div>
  );
}

function AuthGate() {
  const t = useI18n();
  const { status } = useAuth();
  if (status === "loading")
    return (
      <PreShellScreen>
        <StartupLoading label={t("connecting")} detail={t("connectingHint")} />
      </PreShellScreen>
    );
  //: **连不上 ≠ 没登录。** 摆一屏登录页等于告诉用户「你的会话结束了」,而其实令牌还在、
  //: 只是后端这会儿没答应(本机进程,重启和休眠唤醒都是常态)。给他真正有用的两件事:
  //: 再试一次,或者换一个后端地址。
  if (status === "offline") return <OfflineView />;
  if (status === "anonymous") return <LoginView />;
  return <WorkspaceGate />;
}

function OfflineView() {
  const t = useI18n();
  const { retry } = useAuth();
  return (
    <PreShellScreen>
      <div className="grid max-w-sm justify-items-center gap-3 px-6 text-center">
        <PlugZap size={28} className="text-muted-foreground/70" />
        <p className="m-0 text-ui-md font-semibold text-foreground">{t("offlineTitle")}</p>
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("offlineBody")}</p>
        <Button onClick={() => void retry()} className="mt-1">
          {t("retry")}
        </Button>
        <ServerPicker />
      </div>
    </PreShellScreen>
  );
}

const ACTIVE_WORKSPACE_KEY = "mosael:workspace";

function readStoredWorkspaceId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    return null;
  }
}

function persistWorkspaceId(id: string) {
  try {
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, id);
  } catch {
    /* 隐私模式:退化为内存态 */
  }
}

function WorkspaceGate() {
  const t = useI18n();
  const qc = useQueryClient();
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<Workspace[]>("/api/workspaces"),
  });
  // The active workspace is persisted so a refresh — or a newer workspace appearing at
  // list[0] (newest first) — can't switch the user out of the workspace their jobs/projects live in.
  const [activeId, setActiveId] = React.useState<string | null>(
    readStoredWorkspaceId,
  );
  const createWorkspace = useMutation({
    mutationFn: () =>
      api<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: t("workspaceDefault") }),
      }),
    onSuccess: (created) => {
      // 先塞缓存再选中,避免下方兜底效应在列表刷新前把选择弹回 list[0]。
      qc.setQueryData<Workspace[]>(["workspaces"], (old) =>
        old ? [created, ...old] : [created],
      );
      persistWorkspaceId(created.id);
      setActiveId(created.id);
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const list = workspaces.data;
  const workspace =
    list?.find((item) => item.id === activeId) ?? list?.[0] ?? null;

  // Stamp the resolved workspace so the very first load (empty storage) pins list[0].
  React.useEffect(() => {
    if (workspace && workspace.id !== activeId) {
      persistWorkspaceId(workspace.id);
      setActiveId(workspace.id);
    }
  }, [workspace, activeId]);

  const selectWorkspace = React.useCallback((id: string) => {
    persistWorkspaceId(id);
    setActiveId(id);
  }, []);

  if (workspaces.isLoading)
    return (
      <PreShellScreen>
        <StartupLoading
          label={t("workspaceLoading")}
          detail={t("workspaceLoadingHint")}
        />
      </PreShellScreen>
    );
  if (!workspace) {
    return (
      <PreShellScreen>
        <Card className="w-[min(384px,calc(100vw-32px))]">
          <CardContent className="grid justify-items-center gap-4 px-7 pb-[22px] pt-[30px] text-center [&_h1]:m-0 [&_p]:m-0">
            <BrandMark size={56} className="block" />
            <h1>Mosael</h1>
            <p>{t("welcomeText")}</p>
            <Button
              loading={createWorkspace.isPending}
              onClick={() => createWorkspace.mutate()}
            >
              <FolderPlus size={16} /> {t("createWorkspace")}
            </Button>
          </CardContent>
        </Card>
      </PreShellScreen>
    );
  }
  return (
    <Studio
      workspace={workspace}
      workspaces={list ?? []}
      onSelectWorkspace={selectWorkspace}
    />
  );
}

// 路由认哪些页面,和侧栏/面包屑认哪些页面,是同一件事 —— 手抄第三遍就会漏第三次。
const VALID_VIEWS: readonly string[] = STUDIO_VIEWS;

function readHash(): { view: StudioView; projectId: string | null } {
  // Hash routing survives file:// packaging — the fragment never hits HTTP.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const view = VALID_VIEWS.includes(path) ? (path as StudioView) : "home";
  const projectId = new URLSearchParams(query ?? "").get("p");
  return { view, projectId };
}

function writeHash(view: StudioView, projectId: string | null) {
  const query = projectId ? `?p=${projectId}` : "";
  const next = `#/${view}${query}`;
  if (window.location.hash !== next)
    window.history.replaceState(null, "", next);
}

function Studio({
  workspace,
  workspaces,
  onSelectWorkspace,
}: {
  workspace: Workspace;
  workspaces: Workspace[];
  onSelectWorkspace: (id: string) => void;
}) {
  const { voiceDock, setVoiceDock } = usePreferences();
  const t = useI18n();
  const qc = useQueryClient();
  const initial = React.useMemo(readHash, []);
  const [view, setView] = React.useState<StudioView>(initial.view);
  const [projectId, setProjectId] = React.useState<string | null>(
    initial.projectId,
  );

  // Switching workspaces: the open project belongs to the previous workspace, so
  // drop it and return home. The ref skips the initial mount (hash restore).
  const lastWorkspaceRef = React.useRef(workspace.id);
  React.useEffect(() => {
    if (lastWorkspaceRef.current !== workspace.id) {
      lastWorkspaceRef.current = workspace.id;
      setProjectId(null);
      setView("home");
    }
  }, [workspace.id]);

  React.useEffect(() => {
    writeHash(view, projectId);
  }, [view, projectId]);

  React.useEffect(() => {
    const onHashChange = () => {
      const next = readHash();
      setView(next.view);
      if (next.projectId) setProjectId(next.projectId);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const projects = useQuery({
    queryKey: ["projects", workspace.id],
    queryFn: () =>
      api<ProjectWithStats[]>(`/api/projects?workspace_id=${workspace.id}`),
    staleTime: 0,
    refetchInterval: view === "home" ? 5_000 : false,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });
  const project =
    projects.data?.find((item) => item.id === projectId) ??
    projects.data?.[0] ??
    null;

  const openProject = (id: string) => {
    setProjectId(id);
    setView("editor");
  };

  // 智能体说"带你去看看"时,界面真的过去。挂在 Studio 这一层是因为它要跨页面生效,
  // 而且**助手面板收起来时也要管用** —— 免提对话下这条路是唯一的一条。
  useAgentNavigation({
    workspaceId: workspace.id,
    onNavigate: (next, id) => {
      // 白名单在后端 mcp_server._VIEWS 那一侧,这里再挡一道:两边都可能先改。
      if (!VALID_VIEWS.includes(next)) return;
      if (next === "editor" && id) openProject(id);
      else setView(next as StudioView);
    },
  });
  // 新建项目的入口不止首页一处(顶栏切换器、剪辑页空态也有),所以在这里建一次往下传,
  // 而不是各页各建一个 —— 见 useCreateProject 里那条「先写缓存再跳转」的说明。
  const createProject = useCreateProject(workspace.id, openProject);

  // 桌面端外部唤起:mosael:// 深链(只导航)与拖到应用图标上的媒体文件(入库)。
  // 挂在 App 这一层,是因为它要跨页面生效——不能等某个页面挂载了才开始听。
  React.useEffect(() => {
    return listenDesktopDeepLinks((paths) => {
      void Promise.allSettled(
        paths.map((p) => importLocalAsset(workspace.id, p)),
      ).then((settled) => {
        const ok = settled.filter((r) => r.status === "fulfilled").length;
        if (ok) {
          void qc.invalidateQueries({ queryKey: ["assets", workspace.id] });
          toast.success(t("importedAssets").replace("{n}", String(ok)));
        }
        const failed = settled.length - ok;
        if (failed)
          toast.error(t("importFailed").replace("{n}", String(failed)));
      });
    });
  }, [workspace.id, qc, t]);

  return (
    <RecordingProvider workspaceId={workspace.id}>
      <AppShell
        view={view}
        onViewChange={setView}
        workspaceId={workspace.id}
        workspaceName={workspace.name}
        workspaces={workspaces}
        onSelectWorkspace={onSelectWorkspace}
        projectName={project?.name ?? null}
        projects={(projects.data ?? []).map((p) => ({ id: p.id, name: p.name }))}
        currentProjectId={project?.id ?? null}
        onSwitchProject={openProject}
        onCreateProject={() => createProject.mutate()}
        creatingProject={createProject.isPending}
      >
        {view === "home" && (
          <HomeView
            workspace={workspace}
            projects={projects.data ?? []}
            onOpenProject={openProject}
            onCreateProject={() => createProject.mutate()}
            creatingProject={createProject.isPending}
          />
        )}
        {view === "media" && <MediaLibraryView workspace={workspace} />}
        {view === "editor" && (
          <EditorView
            workspace={workspace}
            project={project}
            onCreateProject={() => createProject.mutate()}
            creatingProject={createProject.isPending}
          />
        )}
        {view === "ai" && <AiStudio workspace={workspace} />}
        {view === "publish" && <PublishView workspace={workspace} />}
        {view === "browser-pool" && <BrowserPoolView workspace={workspace} />}
        {view === "settings" && <SettingsView workspace={workspace} />}
        {view === "admin" && <AdminView />}
        {view === "workflows" && <WorkflowsView workspace={workspace} />}
        {view === "boards" && <BoardsView workspace={workspace} />}
        {view === "scheduler" && (
          <SchedulerView workspace={workspace} project={project} />
        )}
        {view === "plugins" && <PluginsView />}
        <CommandPalette
          workspace={workspace}
          projects={projects.data ?? []}
          onNavigate={setView}
          onOpenProject={openProject}
        />
        <ConfirmationCenter workspaceId={workspace.id} />
        {/* 免提浮标挂在**应用级**,不挂在助手面板里:它存在的意义正是"手在别处、面板收起来了"
            的时候还叫得动。默认不浮,由设置里那个开关决定(本地偏好,见 app/preferences)。 */}
        {voiceDock && <VoiceDock workspaceId={workspace.id} onClose={() => setVoiceDock(false)} />}
      </AppShell>
    </RecordingProvider>
  );
}
