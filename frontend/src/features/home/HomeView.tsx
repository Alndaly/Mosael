import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Clock3, Film, FolderPlus, Layers, Pencil, Scissors, Trash2 } from "lucide-react";

import { api, deleteProject, renameProject, type Project, type ProjectWithStats, type Workspace } from "@/api/client";
import { displayWorkspaceName, useI18n, usePreferences } from "@/app/preferences";
import { formatSeconds, formatShortDate } from "@/features/media/MediaLibraryView";
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
  projects: ProjectWithStats[];
  onOpenProject: (projectId: string) => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Project | null>(null);
  const [deleting, setDeleting] = React.useState<Project | null>(null);
  const [search, setSearch] = React.useState("");
  const [sortKey, setSortKey] = React.useState<"updated" | "created" | "name">("updated");

  const visible = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    const matched = projects.filter((project) => query === "" || project.name.toLowerCase().includes(query));
    return [...matched].sort((a, b) => {
      if (sortKey === "name") return a.name.localeCompare(b.name, "zh-CN");
      if (sortKey === "created") return (b.created_at ?? "").localeCompare(a.created_at ?? "");
      return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
    });
  }, [projects, search, sortKey]);
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
      <div className="feature-toolbar media-toolbar">
        <div className="media-toolbar-left">
          <input
            className="toolbar-search"
            value={search}
            placeholder={t("searchProjects")}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="toolbar-select"
            value={sortKey}
            aria-label={t("sortUpdated")}
            onChange={(event) => setSortKey(event.target.value as "updated" | "created" | "name")}
          >
            <option value="updated">{t("sortUpdated")}</option>
            <option value="created">{t("sortCreated")}</option>
            <option value="name">{t("sortName")}</option>
          </select>
        </div>
        <Button size="sm" onClick={() => createProject.mutate()}>
          <FolderPlus size={13} /> {t("createProject")}
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
          <div className="project-grid">
            {visible.map((project) => (
              <ContextMenu key={project.id}>
                <ContextMenuTrigger asChild>
                  <article className="project-card" onDoubleClick={() => onOpenProject(project.id)}>
                    <div className="project-card-body">
                      <strong>{project.name}</strong>
                      <small>{displayWorkspaceName(workspace.name, t)}</small>
                      <div className="project-card-stats">
                        <span title={t("projectStatDuration")}>
                          <Clock3 size={11} />
                          <em className="timecode">{formatSeconds(project.timeline_duration ?? 0)}</em>
                        </span>
                        <span title={t("projectStatAssets")}>
                          <Film size={11} />
                          {t("projectStatAssets").replace("{n}", String(project.asset_count ?? 0))}
                        </span>
                        <span title={t("projectStatSequences")}>
                          <Layers size={11} />
                          {t("projectStatSequences").replace("{n}", String(project.sequence_count ?? 0))}
                        </span>
                      </div>
                      {project.updated_at && (
                        <small className="project-card-updated">
                          {project.created_at && (
                            <>{t("projectCreatedAt").replace("{t}", formatShortDate(project.created_at))} · </>
                          )}
                          {t("projectStatUpdated").replace("{t}", relativeTime(project.updated_at, locale))}
                        </small>
                      )}
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

/** 后端时间是 UTC 无时区标记的 ISO 串;补 Z 再算相对时间。 */
function relativeTime(iso: string, locale: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const deltaSeconds = Math.round((new Date(normalized).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(deltaSeconds);
  if (abs < 60) return rtf.format(Math.trunc(deltaSeconds), "second");
  if (abs < 3600) return rtf.format(Math.trunc(deltaSeconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.trunc(deltaSeconds / 3600), "hour");
  return rtf.format(Math.trunc(deltaSeconds / 86400), "day");
}
