import React from "react";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Film, FolderPlus } from "lucide-react";

import { api, type Project, type Workspace } from "@/api/client";
import { PreferencesProvider, useI18n } from "@/app/preferences";
import { AppShell, type StudioView } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AiStudio } from "@/features/ai-studio/AiStudio";
import { EditorView } from "@/features/editor/EditorView";
import { HomeView } from "@/features/home/HomeView";
import { MediaLibraryView } from "@/features/media/MediaLibraryView";
import { BatchView, KbView, PublishView } from "@/features/planned/PlannedViews";
import { PluginsView } from "@/features/plugins/PluginsView";
import { SchedulerView } from "@/features/scheduler/SchedulerView";
import { SettingsView } from "@/features/settings/SettingsView";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <TooltipProvider delayDuration={300}>
          <WorkspaceGate />
        </TooltipProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  );
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

function Studio({ workspace }: { workspace: Workspace }) {
  const [view, setView] = React.useState<StudioView>("home");
  const [projectId, setProjectId] = React.useState<string | null>(null);
  const projects = useQuery({
    queryKey: ["projects", workspace.id],
    queryFn: () => api<Project[]>(`/api/projects?workspace_id=${workspace.id}`),
  });
  const project = projects.data?.find((item) => item.id === projectId) ?? projects.data?.[0] ?? null;

  const openProject = (id: string) => {
    setProjectId(id);
    setView("editor");
  };

  return (
    <AppShell view={view} onViewChange={setView} workspaceName={workspace.name} projectName={project?.name ?? null}>
      {view === "home" && <HomeView workspace={workspace} projects={projects.data ?? []} onOpenProject={openProject} />}
      {view === "media" && <MediaLibraryView workspace={workspace} project={project} />}
      {view === "editor" && <EditorView workspace={workspace} project={project} />}
      {view === "ai" && <AiStudio workspace={workspace} project={project} />}
      {view === "batch" && <BatchView />}
      {view === "publish" && <PublishView />}
      {view === "kb" && <KbView />}
      {view === "settings" && <SettingsView workspace={workspace} />}
      {view === "scheduler" && <SchedulerView workspace={workspace} project={project} />}
      {view === "plugins" && <PluginsView />}
    </AppShell>
  );
}
