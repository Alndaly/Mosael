import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, FolderOpen, FolderPlus, Pencil, Scissors, Trash2 } from "lucide-react";

import { api, deleteProject, renameProject, type Project, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
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
  const [renaming, setRenaming] = React.useState<Project | null>(null);
  const [deleting, setDeleting] = React.useState<Project | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["projects", workspace.id] });

  const createProject = useMutation({
    mutationFn: () =>
      api<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, name: `${t("projectDefault")} ${projects.length + 1}` }),
      }),
    onSuccess: refresh,
  });
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameProject(id, name),
    onSuccess: () => {
      setRenaming(null);
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: () => {
      setDeleting(null);
      void refresh();
    },
  });

  return (
    <div className="feature-view">
      <div className="feature-toolbar">
        <Button onClick={() => createProject.mutate()}>
          <FolderPlus size={15} /> {t("createProject")}
        </Button>
      </div>

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
          <h2 className="section-label"><FolderOpen size={13} /> {t("homeProjects")}</h2>
          <div className="project-grid">
            {projects.map((project) => (
              <ContextMenu key={project.id}>
                <ContextMenuTrigger asChild>
                  <article className="project-card" onDoubleClick={() => onOpenProject(project.id)}>
                    <div className="project-card-body">
                      <strong>{project.name}</strong>
                      <small>{workspace.name}</small>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => onOpenProject(project.id)}>
                      <Scissors size={13} /> {t("homeOpenEditor")}
                    </Button>
                  </article>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => onOpenProject(project.id)}>
                    <Scissors /> {t("homeOpenEditor")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setRenaming(project)}>
                    <Pencil /> {t("rename")}
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem destructive onSelect={() => setDeleting(project)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </>
      )}

      <RenameDialog
        open={renaming !== null}
        title={t("renameProject")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteProjectBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
