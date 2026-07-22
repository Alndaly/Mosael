import React from "react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, XAxis } from "recharts";

import type { WorkspaceSummary } from "@/api/client";
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
 * 首页图表(shadcn/ui chart + Recharts):近 14 天任务活动(堆叠柱)+ 素材构成(环形)。
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
  input: { label: "", color: "var(--chart-video)" },
  output: { label: "", color: "var(--chart-audio)" },
  other: { label: "", color: "var(--chart-image)" },
} satisfies ChartConfig;

function formatMicros(value: number, currency: string): string {
  if (value <= 0) return `0 ${currency}`;
  const amount = value / 1_000_000;
  if (amount < 1) return `${amount.toFixed(4)} ${currency}`;
  if (amount < 100) return `${amount.toFixed(2)} ${currency}`;
  return `${Math.round(amount).toLocaleString()} ${currency}`;
}

function formatCount(value: number): string {
  if (value < 1_000) return String(value);
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(value < 10_000_000 ? 1 : 0)}m`;
}

export function ActivityChart({ daily }: { daily: WorkspaceSummary["daily"] }) {
  const t = useI18n();
  const max = Math.max(...daily.map((day) => day.succeeded + day.failed));
  if (max === 0) {
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyActivity")}</p>;
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
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground">max {max}</span>} />} />
      </BarChart>
    </ChartContainer>
  );
}

export function UsageCostChart({
  daily,
  currency,
  unknown,
}: {
  daily: WorkspaceSummary["usage_daily"];
  currency: string;
  unknown: number;
}) {
  const t = useI18n();
  const rows = daily ?? [];
  const totalEvents = rows.reduce((sum, day) => sum + day.events, 0);
  const maxCost = Math.max(0, ...rows.map((day) => day.cost_micros));
  if (totalEvents === 0) {
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyUsage")}</p>;
  }
  if (maxCost === 0 && unknown > 0) {
    return (
      <div className="m-0 py-6 text-center text-xs text-muted-foreground">
        <span>{t("homeChartUsageUnpriced").replace("{n}", String(unknown || totalEvents))}</span>
        <button type="button" className="ml-2 inline-flex cursor-pointer items-center border-0 bg-transparent text-primary hover:underline" onClick={() => gotoSettings("provider-pricing")}>
          {t("homeChartUsageConfigurePricing")}
        </button>
      </div>
    );
  }
  if (maxCost === 0) {
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartUsageZeroCost").replace("{n}", String(totalEvents))}</p>;
  }
  const config: ChartConfig = {
    cost: { ...usageConfigBase.cost, label: t("homeLegendCost") },
  };
  const data = rows.map((day) => ({ ...day, day: day.date.slice(5), cost: day.cost_micros }));
  const maxLabel =
    unknown > 0
      ? `${formatMicros(maxCost, currency)} · ${t("homeLegendUnpriced")} ${unknown}`
      : formatMicros(maxCost, currency);

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
          content={<ChartTooltipContent valueFormatter={(value) => formatMicros(Number(value), currency)} />}
        />
        <Bar dataKey="cost" fill="var(--color-cost)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground">max {maxLabel}</span>} />} />
      </BarChart>
    </ChartContainer>
  );
}

export function UsageTokensChart({ daily }: { daily: WorkspaceSummary["usage_token_daily"] }) {
  const t = useI18n();
  const rows = daily ?? [];
  const maxTokens = Math.max(0, ...rows.map((day) => day.total_tokens));
  if (maxTokens === 0) {
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyTokens")}</p>;
  }
  const config: ChartConfig = {
    input: { ...tokenConfigBase.input, label: t("homeLegendInputTokens") },
    output: { ...tokenConfigBase.output, label: t("homeLegendOutputTokens") },
    other: { ...tokenConfigBase.other, label: t("homeLegendOtherTokens") },
  };
  const data = rows.map((day) => {
    const split = day.input_tokens + day.output_tokens;
    return {
      day: day.date.slice(5),
      input: day.input_tokens,
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
        <Bar dataKey="input" stackId="tokens" fill="var(--color-input)" maxBarSize={14} />
        <Bar dataKey="output" stackId="tokens" fill="var(--color-output)" maxBarSize={14} />
        <Bar dataKey="other" stackId="tokens" fill="var(--color-other)" maxBarSize={14} radius={[2, 2, 0, 0]} />
        <ChartLegend
          content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground">max {formatCount(maxTokens)}</span>} />}
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
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyAssets")}</p>;
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
          <span className="text-[10px] text-muted-foreground">{t("homeStatAssets")}</span>
        </div>
      </div>
      {/* 直接标注计数与占比:不用悬停就能读数 */}
      <div className="grid content-center gap-1.5">
        {segments.map((segment) => (
          <div className="flex items-center gap-2 text-[11.5px]" key={segment.kind}>
            <i className="inline-block h-2 w-2 flex-none rounded-full" style={{ background: segment.color }} />
            <span className="truncate text-muted-foreground">{segment.name}</span>
            <span className="ml-auto flex-none tabular-nums">
              <em className="not-italic text-foreground">{segment.count}</em>
              <em className="ml-1.5 not-italic text-[10.5px] text-muted-foreground">
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
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyPublishActivity")}</p>;
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
        <ChartLegend content={<ChartLegendContent extra={<span className="ml-auto inline-flex items-center gap-[5px] tabular-nums text-muted-foreground">max {max}</span>} />} />
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

const PLATFORM_LABELS: Record<string, { zh: string; en: string }> = {
  folder: { zh: "本地目录", en: "Folder" },
  webhook: { zh: "Webhook", en: "Webhook" },
  douyin: { zh: "抖音", en: "Douyin" },
  bilibili: { zh: "B站", en: "Bilibili" },
  xiaohongshu: { zh: "小红书", en: "Xiaohongshu" },
  "weixin-channels": { zh: "视频号", en: "Channels" },
};

function platformLabel(platform: string, locale: string): string {
  const known = PLATFORM_LABELS[platform];
  if (!known) return platform;
  return locale.startsWith("zh") ? known.zh : known.en;
}

export function PublishPlatformsChart({ platforms }: { platforms: WorkspaceSummary["publish_platforms"] }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const entries = Object.entries(platforms)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (total === 0) {
    return <p className="m-0 py-6 text-center text-xs text-muted-foreground">{t("homeChartEmptyPublishPlatforms")}</p>;
  }

  const segments = entries.map(([platform, count], index) => ({
    platform,
    count,
    name: platformLabel(platform, locale),
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
          <span className="text-[11px] text-muted-foreground">{t("publishTabRecords")}</span>
        </div>
        <div className="flex flex-col flex-wrap items-start gap-1 text-[11px] text-muted-foreground">
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
