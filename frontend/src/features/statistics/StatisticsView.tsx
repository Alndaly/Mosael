import React from "react";
import { CollectionTabs, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { RangePicker, useStatRange } from "@/components/layout/RangePicker";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, Clapperboard, Clock3, Coins, Film, Layers, Megaphone, Workflow as WorkflowIcon } from "lucide-react";
import { workspaceSummary, type Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import { gotoSection, gotoSettings } from "@/lib/deepLink";
import { formatCosts } from "@/lib/money";
import { Button } from "@/components/ui/button";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { ActivityChart, AssetKindsChart, PublishActivityChart, PublishPlatformsChart, UsageCostPanel, UsageTokensChart } from "./StatisticsCharts";

const HOME_LIVE_REFRESH_MS = 5_000;
const TABS = ["overview", "publish", "usage"] as const;
type StatsTab = (typeof TABS)[number];
const CARD = "grid min-w-0 content-start gap-4 rounded-lg border border-border bg-panel p-5";
const CARD_TITLE = "m-0 text-ui-sm font-semibold text-foreground";
const STAT_TILE = "grid grid-cols-[minmax(0,1fr)_auto] grid-rows-[auto_auto] items-center gap-x-2 gap-y-3 rounded-lg border border-border bg-panel px-5 py-4 text-left";

/**
 * 顶部一格数字。**只有能落到「解释这个数的那张列表」上的才可点**(`open`);其余只是读数。
 *
 * 去哪儿的判断:
 *   - 项目 → 首页的项目列表;素材 → 素材库(清掉记住的筛选,看全部);工作流 → 工作流**列表**
 *     (不是上次开着的那条详情);近 N 天发布 → 发布记录,筛到「已成功」。都走 `gotoSection`,
 *     即「从页面起点进来」,不走侧栏那种「回到上次的样子」。
 *   - 运行中任务 → 任务中心(它是覆盖层,不换页;进行中的排在最前)。
 *   - 序列:没有列序列的页面(序列在各项目的剪辑页里),此前是打开"最近的项目",
 *     和这个工作区级的总数对不上 —— 不可点。
 *   - AI 花费:解释它的是「AI 用量」tab 里的费用图和按供应商分摊,tab 就在上面一格之遥。它不做成
 *     按钮,因为唯一能**动手**的「N 未定价」就在它里面、单独链到价格规则 —— 按钮里不能再套按钮。
 *   - 近 N 天完成:解释它的就是下方的活动图,跳走反而离开了答案。任务中心只列最近十来组已结束
 *     的任务、不按窗口算,对不上这个数。
 */
type StatTile = {
  key: MessageKey;
  value: React.ReactNode;
  icon: React.ReactNode;
  open?: () => void;
  extra?: { text: string; open?: () => void; openLabel?: MessageKey };
};

/**
 * 统计页。工作区范围,只在打开时每 5 秒刷新。
 *
 * **分三个 tab**:概览(读数、任务活动、素材构成)、发布、AI 用量。三块回答的是三个人的问题 ——
 * 「做了多少东西」「发出去了没有」「花了多少钱」—— 此前挤在同一个两列网格里,想看钱的人要越过
 * 素材构成和发布平台,费用明细又被排进窄的那一列。
 *
 * **窗口只有一个**(7 / 30 / 90 天,和管理页同一个控件):任务、发布、花费都按它算,每块跟着它走的
 * 标题都带着「近 N 天」;项目、素材、序列、工作流和素材构成是当前总数。此前读数是近 7 天、图是
 * 近 14 天,同一页两种窗口。
 */
export function StatisticsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [tab, setTab] = usePersistentTab<StatsTab>("statistics", "overview", TABS);
  const [days, setDays] = useStatRange("statistics-range");
  const summary = useQuery({
    queryKey: ["workspace-summary", workspace.id, days],
    queryFn: () => workspaceSummary(workspace.id, days),
    // 换范围时先留着上一份,不让整页闪回「正在加载」。
    placeholderData: keepPreviousData,
    staleTime: 0,
    refetchInterval: HOME_LIVE_REFRESH_MS,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

  const openTaskCenter = () => window.dispatchEvent(new CustomEvent("mosael:open-tasks"));

  const stats = summary.data;
  // 「近 N 天」取**这份数据自己的**窗口,不取控件上的值:换范围时新数据还没到的那一刻,标题要说的
  // 是图上画的那段时间。
  const windowDays = String(stats?.window_days ?? days);
  const lastDays = t("statLastNDays").replace("{n}", windowDays);
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
          // 而"这个月花了多少"才是打开首页想知道的那个数,次数回答不了它(一次视频生成抵得上
          // 几百次对话)。钱按币种各写一笔(`¥12.30 + US$4.50`):人民币和美元不相加,
          // 此前那个 `usage_cost_micros` 就是把两种钱加在一起、再贴上其中一种单位的数。
          value: formatCosts(stats.usage_costs, locale) || "0",
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
          key: "homeStatJobsDone",
          value: stats.jobs_succeeded,
          icon: <Clock3 size={13} />,
          extra:
            stats.jobs_failed > 0
              ? { text: t("homeStatJobsFailedSuffix").replace("{n}", String(stats.jobs_failed)) }
              : undefined,
        },
        {
          key: "homeStatPublished",
          value: stats.published,
          icon: <Megaphone size={13} />,
          open: () => gotoSection("publish", "succeeded"),
        },
      ]
    : [];

  const titled = (title: string, windowed: boolean) => (
    <>
      {title}
      {windowed && <span className="font-normal text-muted-foreground"> · {lastDays}</span>}
    </>
  );

  return <div className={STUDIO_PAGE} data-statistics-page>
    <div className="grid min-w-0 gap-4">
      <PageHeading title={t("navStatistics")} description={`${workspace.name} · ${t("statsDescription")}`} />
      <div className="border-b border-divider">
        <CollectionTabs
          label={t("statsTabsLabel")}
          value={tab}
          onChange={setTab}
          items={[
            { value: "overview", label: t("statsTabOverview") },
            { value: "publish", label: t("statsTabPublish") },
            { value: "usage", label: t("statsTabUsage") },
          ]}
        />
      </div>
    </div>
    {/* 范围管三个 tab,所以摆在 tab 下、内容上,切 tab 时它不动。 */}
    <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
      <RangePicker days={days} onChange={setDays} />
      <p className="m-0 text-ui-xs text-muted-foreground">{t("statsRangeScope")}</p>
    </div>
    {summary.isPending && <p role="status" className="text-muted-foreground">{t("statsLoading")}</p>}
    {summary.isError && !stats && <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive"><span>{t("statsUnavailable")}</span><Button variant="outline" size="sm" onClick={() => void summary.refetch()}>{t("retry")}</Button></div>}

    {stats && tab === "overview" && (
      <div data-stats-panel="overview" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
        {statTiles.length > 0 && (
          <section className="grid grid-cols-2 gap-3 min-[1000px]:grid-cols-4">
            {statTiles.map((tile) => {
              const body = <>
                <span className="col-start-2 row-start-1 inline-flex text-muted-foreground">{tile.icon}</span>
                {/* 这里现在可能是一串钱("¥0.0004 + US$1.20"),不再只是一个小整数 —— 窄屏上要能截断。 */}
                <strong className="col-start-1 row-start-2 truncate text-3xl font-semibold leading-tight tabular-nums" title={String(tile.value)}>{tile.value}</strong>
                <span className="col-start-1 row-start-1 truncate text-ui-xs text-muted-foreground">
                  {t(tile.key).replace("{n}", windowDays)}
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
        <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4 max-[880px]:grid-cols-1">
          <section className={CARD}>
            <h2 className={CARD_TITLE}>{titled(t("homeChartActivity"), true)}</h2>
            <ActivityChart daily={stats.daily} />
          </section>
          <section className={CARD}>
            <h2 className={CARD_TITLE}>{t("homeChartAssets")}</h2>
            <AssetKindsChart assetKinds={stats.asset_kinds} />
          </section>
        </div>
      </div>
    )}

    {stats && tab === "publish" && (
      <div data-stats-panel="publish" className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] content-start gap-4 max-[880px]:grid-cols-1">
        <section className={CARD}>
          <h2 className={CARD_TITLE}>{titled(t("homeChartPublishActivity"), true)}</h2>
          <PublishActivityChart daily={stats.publish_daily} />
        </section>
        <section className={CARD}>
          <h2 className={CARD_TITLE}>{titled(t("homeChartPublishPlatforms"), true)}</h2>
          <PublishPlatformsChart platforms={stats.publish_platforms} />
        </section>
      </div>
    )}

    {/* 钱和 token 各占满一行:按供应商分摊和九十根柱子都要宽度,此前费用挤在窄的那一列。 */}
    {stats && tab === "usage" && (
      <div data-stats-panel="usage" className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
        <section className={CARD}>
          <UsageCostPanel
            title={titled(t("homeChartUsage"), true)}
            daily={stats.usage_daily}
            costs={stats.usage_costs ?? []}
            unknown={stats.usage_unknown_cost_events}
            unpriced={stats.usage_unpriced}
            byProvider={stats.usage_by_provider}
          />
        </section>
        <section className={CARD}>
          <h2 className={cn(CARD_TITLE, "flex items-center justify-between gap-2")}>
            <span>{titled(t("homeChartTokens"), true)}</span>
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
        </section>
      </div>
    )}
  </div>;
}
