import React from "react";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, FolderPlus } from "lucide-react";

import { api, type ProjectWithStats, type Workspace } from "@/api/client";
import { AuthProvider, useAuth } from "@/app/auth";
import { PreferencesProvider, useI18n, usePreferences } from "@/app/preferences";
import { Toaster } from "sonner";
import { LoginView } from "@/features/auth/LoginView";
import { AppShell, type StudioView } from "@/components/layout/AppShell";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ConfirmationCenter } from "@/components/layout/ConfirmationCenter";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <TooltipProvider delayDuration={300}>
          <AuthProvider>
            <AuthGate />
            <AppToaster />
            <PublishViewBar />
          </AuthProvider>
        </TooltipProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  );
}

/** Electron 内嵌发布视图可见时的顶部返回条(老版 PublishViewBar 的等价):
    视图从 48px 处铺开,这条必须恰好 48px 高,否则露出穿帮。 */
function PublishViewBar() {
  const [state, setState] = React.useState<{ visible: boolean; accountName: string | null }>({
    visible: false,
    accountName: null,
  });
  React.useEffect(() => window.mibuPublish?.onViewState((next) => setState(next)), []);
  if (!state.visible) return null;
  return (
    <div className="publish-view-bar">
      <button type="button" onClick={() => void window.mibuPublish?.hideView()}>
        ← 返回 Mibu
      </button>
      <span>{state.accountName ?? ""}</span>
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

function WorkspaceGate() {
  const t = useI18n();
  const qc = useQueryClient();
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/api/workspaces") });
  const createWorkspace = useMutation({
    mutationFn: () => api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name: t("workspaceDefault") }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces"] }),
  });
  const workspace = workspaces.data?.[0] ?? null;

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
  return <Studio workspace={workspace} />;
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

function Studio({ workspace }: { workspace: Workspace }) {
  const initial = React.useMemo(readHash, []);
  const [view, setView] = React.useState<StudioView>(initial.view);
  const [projectId, setProjectId] = React.useState<string | null>(initial.projectId);

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
      projectName={project?.name ?? null}
    >
      {view === "home" && <HomeView workspace={workspace} projects={projects.data ?? []} onOpenProject={openProject} />}
      {view === "media" && <MediaLibraryView workspace={workspace} project={project} />}
      {view === "editor" && <EditorView workspace={workspace} project={project} />}
      {view === "ai" && <AiStudio workspace={workspace} project={project} />}
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
