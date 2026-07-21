import React from "react";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Film, FolderPlus, Loader2, RotateCw, X } from "lucide-react";

import { api, type ProjectWithStats, type Workspace } from "@/api/client";
import { createMutationCache } from "@/app/mutationErrors";
import { AuthProvider, useAuth } from "@/app/auth";
import { AppearanceProvider } from "@/app/appearance";
import { PreferencesProvider, useI18n, usePreferences } from "@/app/preferences";
import { Toaster, toast } from "sonner";
import { LoginView } from "@/features/auth/LoginView";
import { AppShell, type StudioView } from "@/components/layout/AppShell";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ConfirmationCenter } from "@/components/layout/ConfirmationCenter";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ImagePreviewProvider } from "@/components/ui/image-preview";
import { Input } from "@/components/ui/input";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AiStudio } from "@/features/ai-studio/AiStudio";
import { EditorView } from "@/features/editor/EditorView";
import { HomeView } from "@/features/home/HomeView";
import { MediaLibraryView } from "@/features/media/MediaLibraryView";
import { BatchView } from "@/features/batch/BatchView";
import { PublishView } from "@/features/publish/PublishView";
import { KbView } from "@/features/kb/KbView";
import { PluginsView } from "@/features/plugins/PluginsView";
import { SchedulerView } from "@/features/scheduler/SchedulerView";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";
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
  // 桌面(Electron 无边框窗)样式适配:红绿灯占位、标题拖拽区按 is-desktop/is-mac 生效。
  React.useEffect(() => {
    const desktop = window.mibuDesktop;
    if (!desktop) return;
    const isWin = desktop.platform !== "darwin";
    document.documentElement.classList.add("is-desktop", isWin ? "is-win" : "is-mac");
    // Win/Linux:标题栏三键叠层颜色随主题(mac 无叠层)。跟 <html> 的 .dark 类走。
    if (!isWin || !desktop.setTitleOverlay) return;
    const push = () =>
      desktop.setTitleOverlay!(
        document.documentElement.classList.contains("dark")
          ? { color: "#15181e", symbolColor: "#e7eaf0" }
          : { color: "#ffffff", symbolColor: "#656c78" },
      );
    push();
    const observer = new MutationObserver(push);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  // 全屏时系统窗口控件消失 → 撤掉顶栏为它们预留的边距(mac 76px / Win 148px)。
  React.useEffect(() => {
    const desktop = window.mibuDesktop;
    if (!desktop?.onFullscreen) return;
    return desktop.onFullscreen((fullscreen) => {
      document.documentElement.classList.toggle("is-fullscreen", fullscreen);
    });
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <AppearanceProvider>
          <TooltipProvider delayDuration={300}>
            <AuthProvider>
              <ImagePreviewProvider>
                <AuthGate />
                <AppToaster />
                <PublishViewBar />
              </ImagePreviewProvider>
            </AuthProvider>
          </TooltipProvider>
        </AppearanceProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  );
}

/** Electron 内嵌发布视图可见时的顶部浏览器工具栏:后退/前进/刷新 + 地址栏 + 返回 Mibu。
 *  内嵌视图从 48px 处铺开,这条必须恰好 48px 高,否则中间露出 App 顶栏穿帮。
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
  React.useEffect(() => window.mibuPublish?.onViewState((next) => setState(next)), []);
  // 地址随导航更新,但用户正在输入时不覆盖(否则打字被主进程回报打断)。
  React.useEffect(() => {
    if (!editing) setAddress(state.url ?? "");
  }, [state.url, editing]);
  if (!state.visible) return null;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = address.trim();
    if (value) void window.mibuPublish?.navigate(value);
    (event.currentTarget.querySelector("input") as HTMLInputElement | null)?.blur();
  };

  return (
    <div className="publish-view-bar">
      <div className="pvb-nav titlebar-no-drag">
        <button
          type="button"
          className="pvb-icon"
          disabled={!state.canGoBack}
          onClick={() => void window.mibuPublish?.back()}
          title={t("navBack")}
          aria-label={t("navBack")}
        >
          <ChevronLeft size={16} />
        </button>
        <button
          type="button"
          className="pvb-icon"
          disabled={!state.canGoForward}
          onClick={() => void window.mibuPublish?.forward()}
          title={t("navForward")}
          aria-label={t("navForward")}
        >
          <ChevronRight size={16} />
        </button>
        <button
          type="button"
          className="pvb-icon"
          onClick={() => void window.mibuPublish?.reload()}
          title={state.loading ? t("navStop") : t("navReload")}
          aria-label={state.loading ? t("navStop") : t("navReload")}
        >
          {state.loading ? <X size={15} /> : <RotateCw size={14} />}
        </button>
      </div>
      <form className="pvb-address titlebar-no-drag" onSubmit={submit}>
        {state.loading && <Loader2 size={13} className="pvb-spin" />}
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
        className="pvb-back titlebar-no-drag"
        onClick={() => void window.mibuPublish?.hideView()}
      >
        <ArrowLeft size={14} /> {t("publishBackToMibu")}
      </button>
    </div>
  );
}

/** Sonner 跟随应用主题;样式对齐全平面(细边框、无投影由 CSS 覆盖)。 */
function AppToaster() {
  const { theme } = usePreferences();
  return <Toaster theme={theme} position="bottom-right" gap={8} toastOptions={{ className: "mibu-toast" }} />;
}

function AuthGate() {
  const t = useI18n();
  const { status } = useAuth();
  if (status === "loading") return <div className="center">{t("connecting")}</div>;
  if (status === "anonymous") return <LoginView />;
  return <WorkspaceGate />;
}

const ACTIVE_WORKSPACE_KEY = "mibu:workspace";

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
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/api/workspaces") });
  // The active workspace is persisted so a refresh — or a newer workspace appearing at
  // list[0] (newest first) — can't switch the user out of the workspace their jobs/projects live in.
  const [activeId, setActiveId] = React.useState<string | null>(readStoredWorkspaceId);
  const createWorkspace = useMutation({
    mutationFn: () => api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name: t("workspaceDefault") }) }),
    onSuccess: (created) => {
      persistWorkspaceId(created.id);
      setActiveId(created.id);
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
  const list = workspaces.data;
  const workspace = list?.find((item) => item.id === activeId) ?? list?.[0] ?? null;

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

  if (workspaces.isLoading) return <div className="center">{t("connecting")}</div>;
  if (!workspace) {
    return (
      <div className="center">
        <Card className="welcome">
          <CardContent className="welcome-content">
            <Film size={34} />
            <h1>Mibu</h1>
            <p>{t("welcomeText")}</p>
            <Button onClick={() => createWorkspace.mutate()}>
              <FolderPlus size={16} /> {t("createWorkspace")}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }
  return <Studio workspace={workspace} workspaces={list ?? []} onSelectWorkspace={selectWorkspace} />;
}

const VALID_VIEWS: StudioView[] = ["home", "media", "editor", "ai", "batch", "publish", "kb", "settings", "workflows", "scheduler", "plugins"];

function readHash(): { view: StudioView; projectId: string | null } {
  // Hash routing survives file:// packaging — the fragment never hits HTTP.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const view = (VALID_VIEWS as string[]).includes(path) ? (path as StudioView) : "home";
  const projectId = new URLSearchParams(query ?? "").get("p");
  return { view, projectId };
}

function writeHash(view: StudioView, projectId: string | null) {
  const query = projectId ? `?p=${projectId}` : "";
  const next = `#/${view}${query}`;
  if (window.location.hash !== next) window.history.replaceState(null, "", next);
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
  const initial = React.useMemo(readHash, []);
  const [view, setView] = React.useState<StudioView>(initial.view);
  const [projectId, setProjectId] = React.useState<string | null>(initial.projectId);

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
    queryFn: () => api<ProjectWithStats[]>(`/api/projects?workspace_id=${workspace.id}`),
  });
  const project = projects.data?.find((item) => item.id === projectId) ?? projects.data?.[0] ?? null;

  const openProject = (id: string) => {
    setProjectId(id);
    setView("editor");
  };

  return (
    <AppShell
      view={view}
      onViewChange={setView}
      workspaceId={workspace.id}
      workspaceName={workspace.name}
      workspaces={workspaces}
      onSelectWorkspace={onSelectWorkspace}
      projectName={project?.name ?? null}
    >
      {view === "home" && <HomeView workspace={workspace} projects={projects.data ?? []} onOpenProject={openProject} />}
      {view === "media" && <MediaLibraryView workspace={workspace} />}
      {view === "editor" && <EditorView workspace={workspace} project={project} />}
      {view === "ai" && <AiStudio workspace={workspace} />}
      {view === "batch" && <BatchView workspace={workspace} />}
      {view === "publish" && <PublishView workspace={workspace} />}
      {view === "kb" && <KbView workspace={workspace} />}
      {view === "settings" && <SettingsView workspace={workspace} />}
      {view === "workflows" && <WorkflowsView workspace={workspace} />}
      {view === "scheduler" && <SchedulerView workspace={workspace} project={project} />}
      {view === "plugins" && <PluginsView />}
      <CommandPalette
        workspace={workspace}
        projects={projects.data ?? []}
        onNavigate={setView}
        onOpenProject={openProject}
      />
      <ConfirmationCenter workspaceId={workspace.id} />
    </AppShell>
  );
}
