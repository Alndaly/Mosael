import React from "react";
import { Activity, Coins, FolderOpen, Rocket } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, XAxis } from "recharts";

import type { WorkspaceSummary } from "@/api/client";
import { EmptyState } from "@/components/layout/EmptyState";
import { formatMoney, microsIn, type CostAmount } from "@/lib/money";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/app/chart";
import { gotoSettings } from "@/lib/deepLink";

/**
 * 统计页图表(shadcn/ui chart + Recharts):窗口内任务活动(堆叠柱)+ 素材构成(环形)等。
 * 颜色走 tokens.css 的 --chart-*(dataviz 校验通过的明暗两档),经 ChartConfig
 * 注入为 --color-<key>;文本一律文本色,不穿系列色。
 */

const activityConfig = {
  succeeded: { label: "", color: "var(--chart-ok)" },
  failed: { label: "", color: "var(--chart-fail)" },
} satisfies ChartConfig;

const publishConfigBase = {
  succeeded: { label: "", color: "var(--chart-ok)" },
  failed: { label: "", color: "var(--chart-fail)" },
  active: { label: "", color: "var(--chart-audio)" },
  blocked: { label: "", color: "var(--chart-image)" },
} satisfies ChartConfig;

const usageConfigBase = {
  cost: { label: "", color: "var(--chart-image)" },
} satisfies ChartConfig;

const tokenConfigBase = {
  cacheRead: { label: "", color: "var(--chart-cache)" },
  input: { label: "", color: "var(--chart-video)" },
  output: { label: "", color: "var(--chart-audio)" },
  other: { label: "", color: "var(--chart-image)" },
} satisfies ChartConfig;

function formatCount(value: number): string {
  if (value < 1_000) return String(value);
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(value < 10_000_000 ? 1 : 0)}m`;
}

export function ActivityChart({ daily }: { daily: WorkspaceSummary["daily"] }) {
  const t = useI18n();
  const max = Math.max(...daily.map((day) => day.succeeded + day.failed));
  if (max === 0) {
    return <EmptyState size="compact" icon={<Activity size={15} />} title={t("homeChartEmptyActivity")} />;
  }
  const config: ChartConfig = {
    succeeded: { ...activityConfig.succeeded, label: t("homeLegendSucceeded") },
    failed: { ...activityConfig.failed, label: t("homeLegendFailed") },
  };
  const data = daily.map((day) => ({ ...day, day: day.date.slice(5) }));

  return (
    <ChartContainer config={config} className="h-[150px]">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="30%">
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={6}
          interval="preserveStartEnd"
          minTickGap={48}
        />
        <ChartTooltip cursor={{ fillOpacity: 0.06 }} content={<ChartTooltipContent />} />
        {/* 堆叠:成功在下、失败在上;radius 只圆数据端(顶),基线端直角 */}
        <Bar dataKey="succeeded" stackId="jobs" fill="var(--color-succeeded)" maxBarSize={14} />
        <Bar dataKey="failed" stackId="jobs" fill="var(--color-failed)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground" title={t("homeChartPeakHint")}>{t("homeChartPeak")} {max}</span>} />} />
      </BarChart>
    </ChartContainer>
  );
}

/**
 * 费用这一格:标题行(多币种时带一个币种切换)+ 逐日费用图 + 按供应商分摊。
 *
 * **一张图只画一种钱。**人民币和美元不能叠在同一根柱子上,也不能共用一条纵轴 —— ¥7 和 $1
 * 画成一样高是错的,画成七倍高也是错的。所以多币种时一次看一种,标题行上切换;默认是
 * 主要币种(后端把计过价次数最多的那种排在 costs 第一笔)。图和下面的供应商分摊跟着同一个
 * 选择走,不然柱子是美元、分摊是人民币,两块对不上。
 */
export function UsageCostPanel({
  title,
  daily,
  costs,
  unknown,
  unpriced,
  byProvider,
}: {
  title: React.ReactNode;
  daily: WorkspaceSummary["usage_daily"];
  /** 整段时间的花费,每币种一笔,主要币种在前。 */
  costs: readonly CostAmount[];
  unknown: number;
  unpriced?: WorkspaceSummary["usage_unpriced"];
  byProvider: WorkspaceSummary["usage_by_provider"];
}) {
  const t = useI18n();
  const currencies = costs.map((cost) => cost.currency);
  const [picked, setPicked] = React.useState<string | null>(null);
  // 每 5 秒刷新一次:选中的币种在新回包里没了(不会常见),就回到主要币种。
  const currency = picked && currencies.includes(picked) ? picked : (currencies[0] ?? "");

  return (
    <>
      <h2 className="m-0 flex items-center justify-between gap-2 text-ui-sm font-semibold text-foreground">
        {title}
        {currencies.length > 1 && (
          <span
            className={cn(SEGMENTED_LIST, "min-h-0 p-0.5")}
            role="radiogroup"
            aria-label={t("homeChartUsageCurrency")}
            title={t("homeChartUsageCurrencyHint")}
          >
            {currencies.map((code) => (
              <button
                key={code}
                type="button"
                role="radio"
                aria-checked={code === currency}
                className={cn(segmentedTriggerClass(code === currency), "min-h-6 px-2 text-ui-xs")}
                onClick={() => setPicked(code)}
              >
                {code}
              </button>
            ))}
          </span>
        )}
      </h2>
      <UsageCostChart daily={daily} currency={currency} unknown={unknown} unpriced={unpriced} />
      {/* 看完总额之后的下一个问题就是"钱花在谁身上" —— 这份分摊后端一直在算,
          只是没人读(见前端审计 2.2)。 */}
      <UsageByProvider byProvider={byProvider} currency={currency} />
      {currencies.length > 1 && <p className="m-0 text-ui-2xs text-muted-foreground">{t("homeChartUsageCurrencyHint")}</p>}
    </>
  );
}

export function UsageCostChart({
  daily,
  currency,
  unknown,
  unpriced,
}: {
  daily: WorkspaceSummary["usage_daily"];
  /** 画哪一种钱。空串 = 这段时间一笔都没计上价。 */
  currency: string;
  unknown: number;
  /** 没能定价的「供应商 + 模型」及次数,由后端聚合(见 domain/usage.summarize_usage)。 */
  unpriced?: WorkspaceSummary["usage_unpriced"];
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const rows = daily ?? [];
  const totalEvents = rows.reduce((sum, day) => sum + day.events, 0);
  const maxCost = Math.max(0, ...rows.map((day) => microsIn(day.costs, currency)));
  if (totalEvents === 0) {
    return <EmptyState size="compact" icon={<Coins size={15} />} title={t("homeChartEmptyUsage")} />;
  }
  if (maxCost === 0 && unknown > 0) {
    // **说清缺的是哪个模型的价**,而不是笼统一句「暂无价格规则」——用户配了九条规则却被这么告知,
    // 只会以为功能坏了。真相通常是"这个模型没配":规则挂在别的档案 / 别的模型上。
    // 规则配了、只是币种不一致的那几个,单独注明 —— 对它们说「缺价」同样是错的。
    const missing = (unpriced ?? []).slice(0, 3).map((row) => {
      const name = row.model || row.provider || "?";
      return row.reason === "mixed_currency" ? t("homeChartUsageMixedCurrency").replace("{model}", name) : name;
    });
    return (
      <EmptyState
        size="compact"
        icon={<Coins size={15} />}
        title={t("homeChartUsageUnpriced").replace("{n}", String(unknown || totalEvents))}
        body={
          missing.length > 0
            ? t("homeChartUsageUnpricedModels")
                .replace("{models}", missing.join(t("listSeparator")))
                .replace("{more}", (unpriced?.length ?? 0) > 3 ? t("homeChartUsageUnpricedMore").replace("{n}", String((unpriced?.length ?? 0) - 3)) : "")
            : undefined
        }
        action={
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent text-ui-xs text-primary hover:underline"
            onClick={() => gotoSettings("provider-pricing")}
          >
            {t("homeChartUsageConfigurePricing")}
          </button>
        }
      />
    );
  }
  if (maxCost === 0) {
    return <EmptyState size="compact" icon={<Coins size={15} />} title={t("homeChartUsageZeroCost").replace("{n}", String(totalEvents))} />;
  }
  const config: ChartConfig = {
    cost: { ...usageConfigBase.cost, label: t("homeLegendCost") },
  };
  const data = rows.map((day) => ({ ...day, day: day.date.slice(5), cost: microsIn(day.costs, currency) }));
  const money = (micros: number) => formatMoney(micros, currency, locale);
  const maxLabel = unknown > 0 ? `${money(maxCost)} · ${t("homeLegendUnpriced")} ${unknown}` : money(maxCost);

  return (
    <ChartContainer config={config} className="h-[150px]">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="30%">
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={6}
          interval="preserveStartEnd"
          minTickGap={48}
        />
        <ChartTooltip
          cursor={{ fillOpacity: 0.06 }}
          content={<ChartTooltipContent valueFormatter={(value) => money(Number(value))} />}
        />
        <Bar dataKey="cost" fill="var(--color-cost)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground" title={t("homeChartPeakHint")}>{t("homeChartPeak")} {maxLabel}</span>} />} />
      </BarChart>
    </ChartContainer>
  );
}

export function UsageTokensChart({ daily }: { daily: WorkspaceSummary["usage_token_daily"] }) {
  const t = useI18n();
  const rows = daily ?? [];
  const maxTokens = Math.max(0, ...rows.map((day) => day.total_tokens));
  if (maxTokens === 0) {
    return <EmptyState size="compact" icon={<Coins size={15} />} title={t("homeChartEmptyTokens")} />;
  }
  const config: ChartConfig = {
    cacheRead: { ...tokenConfigBase.cacheRead, label: t("homeLegendCacheReadTokens") },
    input: { ...tokenConfigBase.input, label: t("homeLegendInputTokens") },
    output: { ...tokenConfigBase.output, label: t("homeLegendOutputTokens") },
    other: { ...tokenConfigBase.other, label: t("homeLegendOtherTokens") },
  };
  // 缓存读单独一段,而且垫在最底下:它是"本来要按输入价重新算、结果只花了一成"的那部分,
  // 和 input 挨着才看得出比例。缓存写并进 input —— 它按输入价的 1.25 倍计,性质是"写入成本"
  // 而不是节省,单列会让这张图变成四段谁也读不清。
  const data = rows.map((day) => {
    const cacheRead = day.cache_read_tokens ?? 0;
    const input = day.input_tokens + (day.cache_write_tokens ?? 0);
    const split = input + day.output_tokens + cacheRead;
    return {
      day: day.date.slice(5),
      cacheRead,
      input,
      output: day.output_tokens,
      other: Math.max(0, day.total_tokens - split),
    };
  });

  return (
    <ChartContainer config={config} className="h-[150px]">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="30%">
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={6}
          interval="preserveStartEnd"
          minTickGap={48}
        />
        <ChartTooltip cursor={{ fillOpacity: 0.06 }} content={<ChartTooltipContent valueFormatter={(value) => formatCount(Number(value))} />} />
        <Bar dataKey="cacheRead" stackId="tokens" fill="var(--color-cacheRead)" maxBarSize={14} />
        <Bar dataKey="input" stackId="tokens" fill="var(--color-input)" maxBarSize={14} />
        <Bar dataKey="output" stackId="tokens" fill="var(--color-output)" maxBarSize={14} />
        <Bar dataKey="other" stackId="tokens" fill="var(--color-other)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend
          content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground" title={t("homeChartPeakHint")}>{t("homeChartPeak")} {formatCount(maxTokens)}</span>} />}
        />
      </BarChart>
    </ChartContainer>
  );
}

const KIND_ORDER = [
  { kind: "video", color: "var(--chart-video)", label: "homeKindVideo" },
  { kind: "audio", color: "var(--chart-audio)", label: "homeKindAudio" },
  { kind: "image", color: "var(--chart-image)", label: "homeKindImage" },
] as const;

export function AssetKindsChart({ assetKinds }: { assetKinds: WorkspaceSummary["asset_kinds"] }) {
  const t = useI18n();
  const known = KIND_ORDER.map((entry) => ({ ...entry, count: assetKinds[entry.kind] ?? 0 }));
  const other = Object.entries(assetKinds)
    .filter(([kind]) => !KIND_ORDER.some((entry) => entry.kind === kind))
    .reduce((sum, [, count]) => sum + count, 0);
  const total = known.reduce((sum, entry) => sum + entry.count, 0) + other;
  if (total === 0) {
    return <EmptyState size="compact" icon={<FolderOpen size={15} />} title={t("homeChartEmptyAssets")} />;
  }

  const segments = [
    ...known.filter((entry) => entry.count > 0).map((entry) => ({ ...entry, name: t(entry.label) })),
    ...(other > 0
      ? [{ kind: "other", color: "var(--muted-foreground)", name: t("homeKindOther"), count: other }]
      : []),
  ];
  const config: ChartConfig = Object.fromEntries(
    segments.map((segment) => [segment.kind, { label: segment.name, color: segment.color }]),
  );

  return (
    // 总数进环心、图例行撑满余宽(名称左、计数+占比右):宽卡片上内容占满整行,
    // 不再是环图+一小撮文字挤在左边、右边一大片空白。
    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-5">
      <div className="relative">
        <ChartContainer config={config} className="h-[120px] w-[120px]">
          <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Pie
              data={segments}
              dataKey="count"
              nameKey="kind"
              innerRadius="62%"
              outerRadius="92%"
              paddingAngle={2}
              strokeWidth={0}
              isAnimationActive={false}
            >
              {segments.map((segment) => (
                <Cell key={segment.kind} fill={`var(--color-${segment.kind})`} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
        <div className="pointer-events-none absolute inset-0 grid place-content-center justify-items-center gap-0">
          <strong className="text-lg leading-tight tabular-nums">{total}</strong>
          <span className="text-ui-2xs text-muted-foreground">{t("homeStatAssets")}</span>
        </div>
      </div>
      {/* 直接标注计数与占比:不用悬停就能读数 */}
      <div className="grid content-center gap-1.5">
        {segments.map((segment) => (
          <div className="flex items-center gap-2 text-ui-xs" key={segment.kind}>
            <i className="inline-block h-2 w-2 flex-none rounded-full" style={{ background: segment.color }} />
            <span className="truncate text-muted-foreground">{segment.name}</span>
            <span className="ml-auto flex-none tabular-nums">
              <em className="not-italic text-foreground">{segment.count}</em>
              <em className="ml-1.5 not-italic text-ui-2xs text-muted-foreground">
                {Math.round((segment.count / total) * 100)}%
              </em>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PublishActivityChart({ daily }: { daily: WorkspaceSummary["publish_daily"] }) {
  const t = useI18n();
  const max = Math.max(...daily.map((day) => day.succeeded + day.failed + day.active + day.blocked));
  if (max === 0) {
    return <EmptyState size="compact" icon={<Rocket size={15} />} title={t("homeChartEmptyPublishActivity")} />;
  }
  const config: ChartConfig = {
    succeeded: { ...publishConfigBase.succeeded, label: t("homeLegendSucceeded") },
    failed: { ...publishConfigBase.failed, label: t("homeLegendFailed") },
    active: { ...publishConfigBase.active, label: t("homeLegendActive") },
    blocked: { ...publishConfigBase.blocked, label: t("homeLegendBlocked") },
  };
  const data = daily.map((day) => ({ ...day, day: day.date.slice(5) }));

  return (
    <ChartContainer config={config} className="h-[150px]">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="30%">
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={6}
          interval="preserveStartEnd"
          minTickGap={48}
        />
        <ChartTooltip cursor={{ fillOpacity: 0.06 }} content={<ChartTooltipContent />} />
        <Bar dataKey="succeeded" stackId="publish" fill="var(--color-succeeded)" maxBarSize={14} />
        <Bar dataKey="active" stackId="publish" fill="var(--color-active)" maxBarSize={14} />
        <Bar dataKey="blocked" stackId="publish" fill="var(--color-blocked)" maxBarSize={14} />
        <Bar dataKey="failed" stackId="publish" fill="var(--color-failed)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground" title={t("homeChartPeakHint")}>{t("homeChartPeak")} {max}</span>} />} />
      </BarChart>
    </ChartContainer>
  );
}

const PLATFORM_COLORS = [
  "var(--chart-video)",
  "var(--chart-image)",
  "var(--chart-audio)",
  "var(--chart-ok)",
  "var(--chart-fail)",
] as const;

// 平台 → 图表上的短标签。**这是第三份平台表**(后端 PUBLISH_PLATFORMS、Electron
// PLATFORM_DEFINITIONS 各一份),但它要的是"短到能塞进图例"的名字,和另两份的用途不同:
// 后端那份是给下拉和说明用的完整名。加新平台时三处都要加 —— 漏了这里的后果很轻(退回显示裸
// id,见下面的 fallback),所以没有为它单开一条契约。
const PLATFORM_LABELS: Record<string, MessageKey> = {
  folder: "homeChartPlatformFolder",
  webhook: "homeChartPlatformWebhook",
  douyin: "homeChartPlatformDouyin",
  bilibili: "homeChartPlatformBilibili",
  xiaohongshu: "homeChartPlatformXiaohongshu",
  "weixin-channels": "homeChartPlatformWeixinChannels",
  tiktok: "homeChartPlatformTiktok",
  youtube: "homeChartPlatformYoutube",
};

function platformLabel(platform: string, t: (key: MessageKey) => string): string {
  const known = PLATFORM_LABELS[platform];
  if (!known) return platform;
  return t(known);
}

export function PublishPlatformsChart({ platforms }: { platforms: WorkspaceSummary["publish_platforms"] }) {
  const t = useI18n();
  const entries = Object.entries(platforms)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (total === 0) {
    return <EmptyState size="compact" icon={<Rocket size={15} />} title={t("homeChartEmptyPublishPlatforms")} />;
  }

  const segments = entries.map(([platform, count], index) => ({
    platform,
    count,
    name: platformLabel(platform, t),
    color: PLATFORM_COLORS[index % PLATFORM_COLORS.length],
  }));
  const config: ChartConfig = Object.fromEntries(
    segments.map((segment) => [segment.platform, { label: segment.name, color: segment.color }]),
  );

  return (
    <div className="grid grid-cols-[auto_1fr] items-center gap-3.5">
      <ChartContainer config={config} className="h-[120px] w-[120px]">
        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <ChartTooltip content={<ChartTooltipContent hideLabel />} />
          <Pie
            data={segments}
            dataKey="count"
            nameKey="platform"
            innerRadius="62%"
            outerRadius="92%"
            paddingAngle={2}
            strokeWidth={0}
            isAnimationActive={false}
          >
            {segments.map((segment) => (
              <Cell key={segment.platform} fill={segment.color} />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
      <div className="grid min-w-0 gap-2">
        <div className="flex items-baseline gap-1.5">
          <strong className="text-xl tabular-nums">{total}</strong>
          <span className="text-ui-xs text-muted-foreground">{t("publishTabRecords")}</span>
        </div>
        <div className="flex flex-col flex-wrap items-start gap-1 text-ui-xs text-muted-foreground">
          {segments.map((segment) => (
            <span className="inline-flex items-center gap-[5px]" key={segment.platform}>
              <i className="inline-block h-2 w-2 flex-none rounded-full" style={{ background: segment.color }} /> {segment.name}{" "}
              <em className="not-italic tabular-nums text-foreground">{segment.count}</em>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * 窗口内的花费**按供应商拆开** —— 一行横条,不另占一整块。
 *
 * `usage_by_provider` 一直躺在首页那个回包里没人读:后端每次打开首页都把窗口内的用量事件
 * 算一遍,然后扔掉。而"这个月的钱花在谁身上"恰恰是看完总额之后的下一个问题 —— 此前只能去
 * AI 页一家家点开看。
 *
 * 名字**按金额排**而不是按次数:一次视频生成抵得上几百次对话,按次数排会把最贵的那家
 * 排到最后。只看**当前选中的那种钱**(和上面的图同一个选择):横条是一个整体的各份占比,
 * 人民币和美元拼不成一个整体。
 */
export function UsageByProvider({
  byProvider,
  currency,
}: {
  byProvider: WorkspaceSummary["usage_by_provider"];
  currency: string;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const entries = Object.entries(byProvider ?? {})
    .map(([provider, costs]) => [provider, microsIn(costs, currency)] as const)
    .filter(([, micros]) => micros > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, micros]) => sum + micros, 0);
  // 定不出价的时候总额是 0 —— 那时上面那张图已经在说"缺哪个模型的价"了,这里不再重复一遍。
  if (total === 0) return null;

  return (
    <div className="grid gap-2">
      <div className="flex h-1.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--muted-foreground)_18%,transparent)]">
        {entries.map(([provider, micros], index) => (
          <span
            key={provider}
            className="h-full"
            style={{ width: `${(micros / total) * 100}%`, background: PLATFORM_COLORS[index % PLATFORM_COLORS.length] }}
          />
        ))}
      </div>
      <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-x-4 gap-y-1 p-0">
        {entries.map(([provider, micros], index) => (
          <li key={provider} className="flex items-center gap-1.5 text-ui-2xs text-muted-foreground">
            <span
              className="size-2 shrink-0 rounded-[3px]"
              style={{ background: PLATFORM_COLORS[index % PLATFORM_COLORS.length] }}
            />
            <span className="truncate">{provider}</span>
            <span className="ml-auto shrink-0 tabular-nums text-foreground">{formatMoney(micros, currency, locale)}</span>
          </li>
        ))}
      </ul>
      <p className="m-0 text-ui-2xs text-muted-foreground">{t("homeChartUsageByProvider")}</p>
    </div>
  );
}
