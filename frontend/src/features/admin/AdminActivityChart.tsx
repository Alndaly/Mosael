import React from "react";
import { Activity, CircleAlert } from "lucide-react";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/app/chart";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * 任务活动:每天一根堆叠柱。颜色走 tokens.css 的 --chart-*(dataviz 校验过的明暗两档),
 * 和统计页的活动图同一套;图例、坐标文字一律文本色,不穿系列色。
 */
export function AdminActivityChart({ points, loading, error, onRetry }: {
  points: components["schemas"]["DaySeriesPoint"][];
  loading: boolean; error: boolean; onRetry: () => void;
}) {
  const t = useI18n();
  if (loading) return <Skeleton className="h-[180px] w-full rounded-lg" />;
  if (error) return <EmptyState size="compact" icon={<CircleAlert size={15} />} title={t("adminJobsLoadError")} action={<Button variant="outline" size="xs" onClick={onRetry}>{t("retry")}</Button>} />;
  if (!points.some(point => point.total > 0)) return <EmptyState size="compact" icon={<Activity size={15} />} title={t("adminNoDataTitle")} body={t("adminNoData")} />;

  // The API counts all jobs and failures, not successes: queued/cancelled jobs
  // belong to the remaining total too. Do not present them as successful jobs.
  const data = points.map(point => ({ ...point, other: Math.max(0, point.total - point.failed) }));
  const config = {
    other: { label: t("adminJobsOther"), color: "var(--chart-video)" },
    failed: { label: t("homeLegendFailed"), color: "var(--chart-fail)" },
  };
  return <div className="grid gap-3">
    <ChartContainer config={config} className="h-[180px] w-full">
      <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }} barCategoryGap="25%">
        <CartesianGrid vertical={false} strokeDasharray="0" />
        <XAxis dataKey="day" tickLine={false} axisLine={false} tickMargin={6} interval="preserveStartEnd" minTickGap={40} tickFormatter={(day: string) => day.slice(5)} />
        <ChartTooltip cursor={{ fillOpacity: 0.06 }} content={<ChartTooltipContent />} />
        {/* 堆叠:未失败在下、失败在上;radius 只圆数据端(顶),基线端直角。 */}
        <Bar dataKey="other" stackId="jobs" fill="var(--color-other)" maxBarSize={18} />
        <Bar dataKey="failed" stackId="jobs" fill="var(--color-failed)" maxBarSize={18} radius={[2, 2, 0, 0]} />
      </BarChart>
    </ChartContainer>
    <div className="flex items-center gap-4 text-ui-xs text-muted-foreground">
      <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-[var(--chart-video)]" />{t("adminJobsOther")}</span>
      <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-[var(--chart-fail)]" />{t("homeLegendFailed")}</span>
    </div>
  </div>;
}
