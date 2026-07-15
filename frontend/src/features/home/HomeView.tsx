import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FolderPlus, Scissors } from "lucide-react";

import { api, type Project, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";

export function HomeView({
  workspace,
  projects,
  onOpenProject,
}: {
  workspace: Workspace;
  projects: Project[];
  onOpenProject: (projectId: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const createProject = useMutation({
    mutationFn: () =>
      api<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, name: `${t("projectDefault")} ${projects.length + 1}` }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", workspace.id] }),
  });

  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("navHome")}</h1>
          <p>{workspace.name}</p>
        </div>
        <Button onClick={() => createProject.mutate()}>
          <FolderPlus size={15} /> {t("createProject")}
        </Button>
      </header>

      {projects.length === 0 ? (
        <EmptyState
          icon={<Clapperboard size={22} />}
          title={t("homeEmptyTitle")}
          body={t("homeEmptyBody")}
          action={
            <Button onClick={() => createProject.mutate()}>
              <FolderPlus size={15} /> {t("createProject")}
            </Button>
          }
        />
      ) : (
        <>
          <h2 className="section-label">{t("homeProjects")}</h2>
          <div className="project-grid">
            {projects.map((project) => (
              <article className="project-card" key={project.id}>
                <div className="project-card-body">
                  <strong>{project.name}</strong>
                  <small>{workspace.name}</small>
                </div>
                <Button variant="outline" size="sm" onClick={() => onOpenProject(project.id)}>
                  <Scissors size={13} /> {t("homeOpenEditor")}
                </Button>
              </article>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
