import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  BookText,
  Clapperboard,
  Clock3,
  Coins,
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
import {
  ActivityChart,
  AssetKindsChart,
  PublishActivityChart,
  PublishPlatformsChart,
  UsageCostChart,
  UsageTokensChart,
} from "@/features/home/HomeCharts";
import { HomeHero } from "@/features/home/HomeHero";
import { poemOfToday, randomPoem, type Poem } from "@/features/home/poems";
import { relativeTime } from "@/lib/time";
import { formatSeconds, formatShortDate } from "@/features/media/MediaLibraryView";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";

const HOME_LIVE_REFRESH_MS = 5_000;

export function HomeView({
  workspace,
  projects,
  onOpenProject,
  onCreateProject,
  creatingProject,
}: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  onOpenProject: (projectId: string) => void;
  onCreateProject: () => void;
  creatingProject: boolean;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Project | null>(null);
  const [deleting, setDeleting] = React.useState<Project | null>(null);
  const [search, setSearch] = React.useState("");
  const [sortKey, setSortKey] = React.useState<"updated" | "created" | "name">("updated");

  // 诗从后端取(今日诗词,几十万句);取不到就用本地精选那份 —— 断网不该让首页空一格。
  // 首屏先给本地那句,网络回来了再换,避免开屏闪一下空白。
  const [poem, setPoem] = React.useState<Poem>(poemOfToday);
  const [poemSpins, setPoemSpins] = React.useState(0);
  const [poemLoading, setPoemLoading] = React.useState(false);
  const spinPoem = React.useCallback(async () => {
    setPoemSpins((n) => n + 1);
    setPoemLoading(true);
    try {
      const remote = await api<{ text: string; author: string; source: string; dynasty: string }>("/api/home/poem");
      if (remote?.text) {
        setPoem({ text: remote.text, author: remote.author || remote.dynasty, source: remote.source });
        return;
      }
      setPoem((current) => randomPoem(current));
    } catch {
      setPoem((current) => randomPoem(current));
    } finally {
      setPoemLoading(false);
    }
  }, []);
  React.useEffect(() => {
    void spinPoem();
  }, [spinPoem]);

  // 走字的钟。它不解决任何问题 —— 但盯着首页等渲染/发布跑完的时候,一个还在动的东西
  // 让这一页看起来是活的。每秒一跳,只在首页挂载期间。
  // ?holiday=christmas 之类:节日效果一年只有几天能看到,没有预览入口等于写完没法验。
  // 跟着 hashchange 走 —— 只在挂载时读一次的话,改了地址栏没反应,这个知道也用不了。
  const readHolidayOverride = () =>
    new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("holiday");
  const [holidayOverride, setHolidayOverride] = React.useState(readHolidayOverride);
  React.useEffect(() => {
    const sync = () => setHolidayOverride(readHolidayOverride());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

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
    staleTime: 0,
    refetchInterval: HOME_LIVE_REFRESH_MS,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  React.useEffect(() => {
    void qc.invalidateQueries({ queryKey: ["workspace-summary", workspace.id] });
    void qc.invalidateQueries({ queryKey: ["projects", workspace.id] });
  }, [qc, workspace.id]);

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
  const openTaskCenter = () => window.dispatchEvent(new CustomEvent("openstudio:open-tasks"));

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
        { key: "homeStatRunningJobs", value: stats.running_jobs, icon: <Activity size={13} />, action: openTaskCenter },
        {
          key: "homeStatAiUsage",
          value: stats.usage_event_count,
          icon: <Coins size={13} />,
          goto: "/ai",
          extra:
            stats.usage_unknown_cost_events > 0
              ? t("homeStatUsageUnknownSuffix").replace("{n}", String(stats.usage_unknown_cost_events))
              : undefined,
        },
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
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <HomeHero
        greeting={t(greetingKey)}
        workspaceName={displayWorkspaceName(workspace.name, t)}
        now={now}
        poem={poem}
        poemLoading={poemLoading}
        poemEgg={poemSpins > 0 && poemSpins % 10 === 0 ? t("homePoemEgg") : undefined}
        onRefreshPoem={() => void spinPoem()}
        holidayOverride={holidayOverride}
      />

      {statTiles.length > 0 && (
        <section className="mb-3 grid grid-cols-[repeat(auto-fit,minmax(128px,1fr))] gap-2.5">
          {statTiles.map((tile) => (
            <button
              type="button"
              className="grid cursor-pointer grid-cols-[auto_1fr] grid-rows-[auto_auto] items-center gap-x-2 rounded-lg border border-border bg-panel px-3 py-2 text-left hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
              key={tile.key}
              onClick={() => {
                if ("goto" in tile && tile.goto) gotoRecord(tile.goto);
                else if ("action" in tile && tile.action) tile.action();
              }}
            >
              <span className="row-span-2 inline-flex text-muted-foreground">{tile.icon}</span>
              <strong className="text-base font-[650] leading-[1.2] tabular-nums">{tile.value}</strong>
              <span className="truncate text-[11px] text-muted-foreground">
                {t(tile.key)}
                {"extra" in tile && tile.extra ? <em className="not-italic text-destructive"> · {tile.extra}</em> : null}
              </span>
            </button>
          ))}
        </section>
      )}

      {stats && (
        <section className="mb-3 grid grid-cols-[2fr_1fr] gap-2.5 max-[880px]:grid-cols-1">
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartActivity")}</h2>
            <ActivityChart daily={stats.daily} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartAssets")}</h2>
            <AssetKindsChart assetKinds={stats.asset_kinds} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartPublishActivity")}</h2>
            <PublishActivityChart daily={stats.publish_daily} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartPublishPlatforms")}</h2>
            <PublishPlatformsChart platforms={stats.publish_platforms} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartUsage")}</h2>
            <UsageCostChart daily={stats.usage_daily} currency={stats.usage_currency} unknown={stats.usage_unknown_cost_events} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-3.5 pb-2 pt-2.5">
            <h2 className="m-0 flex items-center justify-between gap-2 text-xs font-[650] text-muted-foreground">
              {t("homeChartTokens")}
              {/* 命中率放标题行:图上看的是"哪天多哪天少",这个数回答的是"整段时间省了多少",
                  两者不该抢同一块地方。只在真有缓存时出现 —— 恒定的 0% 只是噪音。 */}
              {stats.usage_cache_hit_ratio > 0 && (
                <span
                  className="font-normal tabular-nums text-muted-foreground"
                  title={t("homeCacheHitHint")}
                >
                  {t("homeCacheHit")} {Math.round(stats.usage_cache_hit_ratio * 100)}%
                </span>
              )}
            </h2>
            <UsageTokensChart daily={stats.usage_token_daily} />
          </div>
        </section>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Input
            ref={searchRef}
            className="h-8 w-48 rounded-md border border-border bg-field px-2.5 text-xs text-foreground transition-[border-color] duration-100 placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none"
            value={search}
            placeholder={t("searchProjects")}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select value={sortKey} onValueChange={(value) => setSortKey(value as "updated" | "created" | "name")}>
            <SelectTrigger className="h-8 w-auto min-w-32 bg-field text-xs" aria-label={t("sortUpdated")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-w-none">
              <SelectItem value="updated">{t("sortUpdated")}</SelectItem>
              <SelectItem value="created">{t("sortCreated")}</SelectItem>
              <SelectItem value="name">{t("sortName")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button size="sm" onClick={onCreateProject} disabled={creatingProject}>
          <FolderPlus size={13} /> {t("createProject")}
        </Button>
      </div>

      {projects.length === 0 ? (
        <EmptyState
          icon={<Clapperboard size={22} />}
          title={t("homeEmptyTitle")}
          body={t("homeEmptyBody")}
          action={
            <Button onClick={onCreateProject} disabled={creatingProject}>
              <FolderPlus size={15} /> {t("createProject")}
            </Button>
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-2.5">
            {visible.map((project) => (
              <ContextMenu key={project.id}>
                <ContextMenuTrigger asChild>
                  <article className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border border-border bg-panel p-3 shadow-[var(--shadow-panel)] transition-[border-color] duration-100 hover:border-border-strong [[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] [[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)]" onDoubleClick={() => onOpenProject(project.id)}>
                    <div className="min-w-0">
                      <strong className="block truncate text-[13px] font-semibold">{project.name}</strong>
                      <small className="mt-0.5 block text-xs text-muted-foreground">{displayWorkspaceName(workspace.name, t)}</small>
                    </div>
                    <div className="flex flex-wrap items-center gap-2.5 text-[11.5px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1 whitespace-nowrap" title={t("projectStatDuration")}>
                        <Clock3 size={11} />
                        <em className="timecode not-italic">{formatSeconds(project.timeline_duration ?? 0)}</em>
                      </span>
                      <span className="inline-flex items-center gap-1 whitespace-nowrap" title={t("projectStatAssets")}>
                        <Film size={11} />
                        {t("projectStatAssets").replace("{n}", String(project.asset_count ?? 0))}
                      </span>
                      <span className="inline-flex items-center gap-1 whitespace-nowrap" title={t("projectStatSequences")}>
                        <Layers size={11} />
                        {t("projectStatSequences").replace("{n}", String(project.sequence_count ?? 0))}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-1.5 border-t border-border pt-2.5">
                      <small className="m-0 min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
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
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(project)}>
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
