import React from "react";
import { PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { useQuery } from "@tanstack/react-query";
import { Activity, Clapperboard, Clock3, Coins, Film, Layers, Megaphone, Workflow as WorkflowIcon } from "lucide-react";
import { workspaceSummary, type Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { gotoSection, gotoSettings } from "@/lib/deepLink";
import { formatMicros } from "@/lib/money";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ActivityChart, AssetKindsChart, PublishActivityChart, PublishPlatformsChart, UsageByProvider, UsageCostChart, UsageTokensChart } from "./StatisticsCharts";

const HOME_LIVE_REFRESH_MS = 5_000;
const STAT_TILE = "grid grid-cols-[minmax(0,1fr)_auto] grid-rows-[auto_auto] items-center gap-x-2 gap-y-3 rounded-lg border border-border bg-panel px-5 py-4 text-left";

/**
 * 顶部一格数字。**只有能落到「解释这个数的那张列表」上的才可点**(`open`);其余只是读数。
 *
 * 去哪儿的判断:
 *   - 项目 → 首页的项目列表;素材 → 素材库(清掉记住的筛选,看全部);工作流 → 工作流**列表**
 *     (不是上次开着的那条详情);近 7 天发布 → 发布记录,筛到「已成功」。都走 `gotoSection`,
 *     即「从页面起点进来」,不走侧栏那种「回到上次的样子」。
 *   - 运行中任务 → 任务中心(它是覆盖层,不换页;进行中的排在最前)。
 *   - 序列:没有列序列的页面(序列在各项目的剪辑页里),此前是打开"最近的项目",
 *     和这个工作区级的总数对不上 —— 不可点。
 *   - AI 用量、近 7 天完成:解释它们的就是本页下方的费用 / 活动图,跳走反而离开了答案。
 *     任务中心只列最近十来组已结束的任务、不按 7 天算,对不上这个数。唯一能**动手**的是
 *     「N 未定价」,它单独链到价格规则。
 */
type StatTile = {
  key: MessageKey;
  value: React.ReactNode;
  icon: React.ReactNode;
  open?: () => void;
  extra?: { text: string; open?: () => void; openLabel?: MessageKey };
};

/** All statistics remain workspace-scoped and refresh only while this view is open. */
export function StatisticsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const summary = useQuery({
    queryKey: ["workspace-summary", workspace.id],
    queryFn: () => workspaceSummary(workspace.id),
    staleTime: 0,
    refetchInterval: HOME_LIVE_REFRESH_MS,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  const openTaskCenter = () => window.dispatchEvent(new CustomEvent("mosael:open-tasks"));

  const stats = summary.data;
  const statTiles: StatTile[] = stats
    ? [
        { key: "homeStatProjects", value: stats.project_count, icon: <Clapperboard size={13} />, open: () => gotoSection("home") },
        { key: "homeStatAssets", value: stats.asset_count, icon: <Film size={13} />, open: () => gotoSection("media") },
        { key: "homeStatSequences", value: stats.sequence_count, icon: <Layers size={13} /> },
        { key: "homeStatWorkflows", value: stats.workflow_count, icon: <WorkflowIcon size={13} />, open: () => gotoSection("workflows") },
        { key: "homeStatRunningJobs", value: stats.running_jobs, icon: <Activity size={13} />, open: openTaskCenter },
        {
          key: "homeStatAiUsage",
          // **这块磁贴显示的是钱,不是次数。** 它此前显示 `usage_event_count`(调用了几次),
          // 而同一个回包里就躺着 `usage_cost_micros` 和配套的 `usage_currency` —— 后者被读了
          // (传给费用图),前者没有:"货币单位"用上了,"钱数"没用上。而"这个月花了多少"
          // 才是打开首页想知道的那个数,次数回答不了它(一次视频生成抵得上几百次对话)。
          value: formatMicros(stats.usage_cost_micros, stats.usage_currency),
          icon: <Coins size={13} />,
          extra:
            stats.usage_unknown_cost_events > 0
              ? {
                  text: t("homeStatUsageUnknownSuffix").replace("{n}", String(stats.usage_unknown_cost_events)),
                  open: () => gotoSettings("provider-pricing"),
                  openLabel: "homeChartUsageConfigurePricing",
                }
              : undefined,
        },
        {
          key: "homeStatWeekDone",
          value: stats.week_jobs_succeeded,
          icon: <Clock3 size={13} />,
          extra:
            stats.week_jobs_failed > 0
              ? { text: t("homeStatWeekFailedSuffix").replace("{n}", String(stats.week_jobs_failed)) }
              : undefined,
        },
        {
          key: "homeStatWeekPublished",
          value: stats.week_published,
          icon: <Megaphone size={13} />,
          open: () => gotoSection("publish", "succeeded"),
        },
      ]
    : [];

  return <div className={STUDIO_PAGE}>
    <PageHeading title={t("navStatistics")} description={`${workspace.name} · ${t("statsDescription")}`} />
    {summary.isPending && <p role="status" className="text-muted-foreground">{t("statsLoading")}</p>}
    {summary.isError && <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive"><span>{t("statsUnavailable")}</span><Button variant="outline" size="sm" onClick={() => void summary.refetch()}>{t("retry")}</Button></div>}
      {statTiles.length > 0 && (
        <section className="grid grid-cols-2 gap-3 min-[1000px]:grid-cols-4">
          {statTiles.map((tile) => {
            const body = <>
              <span className="col-start-2 row-start-1 inline-flex text-muted-foreground">{tile.icon}</span>
              {/* 这里现在可能是一串钱("0.0004 USD"),不再只是一个小整数 —— 窄屏上要能截断。 */}
              <strong className="col-start-1 row-start-2 truncate text-3xl font-semibold leading-tight tabular-nums" title={String(tile.value)}>{tile.value}</strong>
              <span className="col-start-1 row-start-1 truncate text-ui-xs text-muted-foreground">
                {t(tile.key)}
                {tile.extra && (
                  <em className="not-italic text-destructive">
                    {" · "}
                    {tile.extra.open ? (
                      <button
                        type="button"
                        className="cursor-pointer border-0 bg-transparent p-0 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                        title={tile.extra.openLabel && t(tile.extra.openLabel)}
                        onClick={tile.extra.open}
                      >
                        {tile.extra.text}
                      </button>
                    ) : tile.extra.text}
                  </em>
                )}
              </span>
            </>;
            // 不可点的就是一块读数:没有按钮角色、没有手型、悬停不变边框 —— 看起来能点却没反应,
            // 比不能点更糟。
            return tile.open ? (
              <button type="button" key={tile.key} className={cn(STAT_TILE, "cursor-pointer hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring")} onClick={tile.open}>
                {body}
              </button>
            ) : (
              <div key={tile.key} className={STAT_TILE} data-stat={tile.key}>{body}</div>
            );
          })}
        </section>
      )}

      {stats && (
        <section className="grid grid-cols-[2fr_1fr] gap-4 max-[880px]:grid-cols-1">
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 text-ui-sm font-semibold text-foreground">{t("homeChartActivity")}</h2>
            <ActivityChart daily={stats.daily} />
          </div>
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 text-ui-sm font-semibold text-foreground">{t("homeChartAssets")}</h2>
            <AssetKindsChart assetKinds={stats.asset_kinds} />
          </div>
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 text-ui-sm font-semibold text-foreground">{t("homeChartPublishActivity")}</h2>
            <PublishActivityChart daily={stats.publish_daily} />
          </div>
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 text-ui-sm font-semibold text-foreground">{t("homeChartPublishPlatforms")}</h2>
            <PublishPlatformsChart platforms={stats.publish_platforms} />
          </div>
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 text-ui-sm font-semibold text-foreground">{t("homeChartUsage")}</h2>
            <UsageCostChart
              daily={stats.usage_daily}
              currency={stats.usage_currency}
              unknown={stats.usage_unknown_cost_events}
              unpriced={stats.usage_unpriced}
            />
            {/* 看完总额之后的下一个问题就是"钱花在谁身上" —— 这份分摊后端一直在算,
                只是没人读(见前端审计 2.2)。 */}
            <UsageByProvider byProvider={stats.usage_by_provider} currency={stats.usage_currency} />
          </div>
          <div className="grid content-start gap-4 rounded-lg border border-border bg-panel p-5">
            <h2 className="m-0 flex items-center justify-between gap-2 text-ui-sm font-semibold text-foreground">
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
