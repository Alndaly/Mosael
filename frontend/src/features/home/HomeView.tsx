import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  BookText,
  Clapperboard,
  Clock3,
  Film,
  FolderPlus,
  Layers,
  Megaphone,
  Pencil,
  RefreshCcw,
  Scissors,
  Trash2,
  Workflow as WorkflowIcon,
} from "lucide-react";

import { api, deleteProject, renameProject, workspaceSummary, type Project, type ProjectWithStats, type Workspace } from "@/api/client";
import { displayWorkspaceName, useI18n, usePreferences } from "@/app/preferences";
import { gotoRecord } from "@/lib/deepLink";
import { ActivityChart, AssetKindsChart, PublishActivityChart, PublishPlatformsChart } from "@/features/home/HomeCharts";
import { poemOfToday, randomPoem, type Poem } from "@/features/home/poems";
import { relativeTime } from "@/lib/time";
import { formatSeconds, formatShortDate } from "@/features/media/MediaLibraryView";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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

  const [poem, setPoem] = React.useState<Poem>(poemOfToday);
  const [poemSpins, setPoemSpins] = React.useState(0);
  const spinPoem = () => {
    setPoem((current) => randomPoem(current));
    setPoemSpins((n) => n + 1);
  };

  const greetingKey = React.useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 5) return "homeGreetingDawn" as const;
    if (hour < 11) return "homeGreetingMorning" as const;
    if (hour < 13) return "homeGreetingNoon" as const;
    if (hour < 18) return "homeGreetingAfternoon" as const;
    return "homeGreetingEvening" as const;
  }, []);

  const summary = useQuery({
    queryKey: ["workspace-summary", workspace.id],
    queryFn: () => workspaceSummary(workspace.id),
    staleTime: 30_000,
  });

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
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setRenaming(null);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
  });

  // 每块磁贴都是入口:goto 是 hash 路由,action 是页面内动作(深链事件/打开项目)。
  const searchRef = React.useRef<HTMLInputElement | null>(null);
  const latestProject = React.useMemo(
    () => [...projects].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))[0],
    [projects],
  );
  const openTaskCenter = () => window.dispatchEvent(new CustomEvent("mibu:open-tasks"));

  const stats = summary.data;
  const statTiles = stats
    ? ([
        {
          key: "homeStatProjects",
          value: stats.project_count,
          icon: <Clapperboard size={13} />,
          action: () => searchRef.current?.focus(),
        },
        { key: "homeStatAssets", value: stats.asset_count, icon: <Film size={13} />, goto: "/media" },
        {
          key: "homeStatSequences",
          value: stats.sequence_count,
          icon: <Layers size={13} />,
          action: () => latestProject && onOpenProject(latestProject.id),
        },
        { key: "homeStatWorkflows", value: stats.workflow_count, icon: <WorkflowIcon size={13} />, goto: "/workflows" },
        { key: "homeStatKbDocs", value: stats.kb_document_count, icon: <BookOpen size={13} />, goto: "/kb" },
        { key: "homeStatRunningJobs", value: stats.running_jobs, icon: <Activity size={13} />, action: openTaskCenter },
        {
          key: "homeStatWeekDone",
          value: stats.week_jobs_succeeded,
          icon: <Clock3 size={13} />,
          action: openTaskCenter,
          extra:
            stats.week_jobs_failed > 0
              ? t("homeStatWeekFailedSuffix").replace("{n}", String(stats.week_jobs_failed))
              : undefined,
        },
        { key: "homeStatWeekPublished", value: stats.week_published, icon: <Megaphone size={13} />, goto: "/publish" },
      ] as const)
    : [];

  return (
    <div className="feature-view">
      <section className="home-hero">
        <div className="home-hero-greeting">
          <h1>{t(greetingKey)}</h1>
          <small>{displayWorkspaceName(workspace.name, t)}</small>
        </div>
        <figure className="home-poem" aria-live="polite">
          <BookText size={13} className="home-poem-icon" />
          {poemSpins > 0 && poemSpins % 10 === 0 ? (
            <blockquote>{t("homePoemEgg")}</blockquote>
          ) : (
            <>
              <blockquote>{poem.text}</blockquote>
              <figcaption>
                {poem.author} · 《{poem.source}》
              </figcaption>
            </>
          )}
          <button type="button" className="home-poem-refresh" aria-label={t("homePoemRefresh")} onClick={spinPoem}>
            <RefreshCcw size={12} />
          </button>
        </figure>
      </section>

      {statTiles.length > 0 && (
        <section className="home-stats">
          {statTiles.map((tile) => (
            <button
              type="button"
              className="home-stat"
              key={tile.key}
              onClick={() => {
                if ("goto" in tile && tile.goto) gotoRecord(tile.goto);
                else if ("action" in tile && tile.action) tile.action();
              }}
            >
              <span className="home-stat-icon">{tile.icon}</span>
              <strong className="home-stat-value">{tile.value}</strong>
              <span className="home-stat-label">
                {t(tile.key)}
                {"extra" in tile && tile.extra ? <em className="home-stat-extra"> · {tile.extra}</em> : null}
              </span>
            </button>
          ))}
        </section>
      )}

      {stats && (
        <section className="home-charts">
          <div className="home-chart">
            <h2 className="home-chart-title">{t("homeChartActivity")}</h2>
            <ActivityChart daily={stats.daily} />
          </div>
          <div className="home-chart">
            <h2 className="home-chart-title">{t("homeChartAssets")}</h2>
            <AssetKindsChart assetKinds={stats.asset_kinds} />
          </div>
          <div className="home-chart">
            <h2 className="home-chart-title">{t("homeChartPublishActivity")}</h2>
            <PublishActivityChart daily={stats.publish_daily} />
          </div>
          <div className="home-chart">
            <h2 className="home-chart-title">{t("homeChartPublishPlatforms")}</h2>
            <PublishPlatformsChart platforms={stats.publish_platforms} />
          </div>
        </section>
      )}

      <div className="feature-toolbar media-toolbar">
        <div className="media-toolbar-left">
          <input
            ref={searchRef}
            className="toolbar-search"
            value={search}
            placeholder={t("searchProjects")}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select value={sortKey} onValueChange={(value) => setSortKey(value as "updated" | "created" | "name")}>
            <SelectTrigger aria-label={t("sortUpdated")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated">{t("sortUpdated")}</SelectItem>
              <SelectItem value="created">{t("sortCreated")}</SelectItem>
              <SelectItem value="name">{t("sortName")}</SelectItem>
            </SelectContent>
          </Select>
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
                    </div>
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
                    <div className="project-card-foot">
                      <small className="project-card-updated">
                        {project.created_at && (
                          <>{t("projectCreatedAt").replace("{t}", formatShortDate(project.created_at))} · </>
                        )}
                        {project.updated_at && t("projectStatUpdated").replace("{t}", relativeTime(project.updated_at, locale))}
                      </small>
                      <Button variant="outline" size="sm" onClick={() => onOpenProject(project.id)}>
                        <Scissors size={13} /> {t("homeOpenEditor")}
                      </Button>
                    </div>
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
