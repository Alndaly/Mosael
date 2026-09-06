import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Clapperboard, Clock3, Coins, Film, Layers, Megaphone, Workflow as WorkflowIcon } from "lucide-react";
import { workspaceSummary, type ProjectWithStats, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { gotoRecord } from "@/lib/deepLink";
import { Button } from "@/components/ui/button";
import { ActivityChart, AssetKindsChart, PublishActivityChart, PublishPlatformsChart, UsageCostChart, UsageTokensChart } from "./HomeCharts";

const HOME_LIVE_REFRESH_MS = 5_000;

/** All statistics remain workspace-scoped and refresh only while this view is open. */
export function StatisticsView({ workspace, projects, onOpenProject }: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  onOpenProject: (id: string) => void;
}) {
  const t = useI18n();
  const summary = useQuery({
    queryKey: ["workspace-summary", workspace.id],
    queryFn: () => workspaceSummary(workspace.id),
    staleTime: 0,
    refetchInterval: HOME_LIVE_REFRESH_MS,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  const latestProject = React.useMemo(
    () => [...projects].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))[0],
    [projects],
  );
  const openTaskCenter = () => window.dispatchEvent(new CustomEvent("mosael:open-tasks"));

  const stats = summary.data;
  const statTiles = stats
    ? ([
        {
          key: "homeStatProjects",
          value: stats.project_count,
          icon: <Clapperboard size={13} />,
          goto: "/home",
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

  return <div className="grid h-full min-h-0 content-start gap-6 overflow-auto p-6 xl:p-8">
    <div><h2 className="m-0 text-3xl font-semibold tracking-tight">{t("navStatistics")}</h2><p className="mb-0 mt-2 text-ui-md text-muted-foreground">{workspace.name} · {t("statsDescription")}</p></div>
    {summary.isPending && <p role="status" className="text-muted-foreground">{t("statsLoading")}</p>}
    {summary.isError && <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive"><span>{t("statsUnavailable")}</span><Button variant="outline" size="sm" onClick={() => void summary.refetch()}>{t("retry")}</Button></div>}
      {statTiles.length > 0 && (
        <section className="grid grid-cols-2 gap-3 min-[1000px]:grid-cols-4">
          {statTiles.map((tile) => (
            <button
              type="button"
              className="grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] grid-rows-[auto_auto] items-center gap-x-2 gap-y-3 rounded-lg border border-border bg-panel px-5 py-4 text-left hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
              key={tile.key}
              onClick={() => {
                if ("goto" in tile && tile.goto) gotoRecord(tile.goto);
                else if ("action" in tile && tile.action) tile.action();
              }}
            >
              <span className="col-start-2 row-start-1 inline-flex text-muted-foreground">{tile.icon}</span>
              <strong className="col-start-1 row-start-2 text-3xl font-semibold leading-tight tabular-nums">{tile.value}</strong>
              <span className="col-start-1 row-start-1 truncate text-ui-xs text-muted-foreground">
                {t(tile.key)}
                {"extra" in tile && tile.extra ? <em className="not-italic text-destructive"> · {tile.extra}</em> : null}
              </span>
            </button>
          ))}
        </section>
      )}

      {stats && (
        <section className="grid grid-cols-[2fr_1fr] gap-4 max-[880px]:grid-cols-1">
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartActivity")}</h2>
            <ActivityChart daily={stats.daily} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartAssets")}</h2>
            <AssetKindsChart assetKinds={stats.asset_kinds} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartPublishActivity")}</h2>
            <PublishActivityChart daily={stats.publish_daily} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartPublishPlatforms")}</h2>
            <PublishPlatformsChart platforms={stats.publish_platforms} />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
            <h2 className="m-0 text-xs font-[650] text-muted-foreground">{t("homeChartUsage")}</h2>
            <UsageCostChart
              daily={stats.usage_daily}
              currency={stats.usage_currency}
              unknown={stats.usage_unknown_cost_events}
              unpriced={stats.usage_unpriced}
            />
          </div>
          <div className="grid content-start gap-1.5 rounded-lg border border-border bg-panel px-5 pb-4 pt-4">
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

  </div>;
}
