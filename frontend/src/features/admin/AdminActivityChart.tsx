import React from "react";
import { Activity, CircleAlert } from "lucide-react";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/app/chart";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function AdminActivityChart({ points, loading, error, onRetry }: {
  points: components["schemas"]["DaySeriesPoint"][];
  loading: boolean; error: boolean; onRetry: () => void;
}) {
  const t = useI18n();
  if (loading) return <Skeleton className="mt-3 h-36 w-full rounded-lg" />;
  if (error) return <EmptyState size="compact" className="my-3 max-w-none rounded-lg border border-border bg-panel" icon={<CircleAlert />} title={t("adminJobsLoadError")} action={<Button variant="outline" size="sm" onClick={onRetry}>{t("retry")}</Button>} />;
  if (!points.some(point => point.total > 0)) return <EmptyState size="compact" className="my-3 max-w-none gap-2 rounded-lg border border-border bg-panel py-6" icon={<Activity />} title={t("adminNoDataTitle")} body={t("adminNoData")} />;

  // The API counts all jobs and failures, not successes: queued/cancelled jobs
  // belong to the remaining total too. Do not present them as successful jobs.
  const data = points.map(point => ({ ...point, other: Math.max(0, point.total - point.failed) }));
  const config = {
    other: { label: t("adminJobsOther"), color: "var(--primary)" },
    failed: { label: t("homeLegendFailed"), color: "var(--destructive)" },
  };
  return <div className="grid gap-3 pt-4">
    <div className="flex items-center gap-4 text-ui-xs text-muted-foreground">
      <span className="flex items-center gap-2"><span className="size-2 rounded-sm bg-primary" />{t("adminJobsOther")}</span>
      <span className="flex items-center gap-2"><span className="size-2 rounded-sm bg-destructive" />{t("homeLegendFailed")}</span>
    </div>
    <ChartContainer config={config} className="h-[180px] w-full">
      <BarChart data={data} barSize={24}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="day" tickLine={false} axisLine={false} tickFormatter={(day: string) => day.slice(5)} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Bar dataKey="other" stackId="jobs" fill="var(--color-other)" radius={[0, 0, 2, 2]} />
        <Bar dataKey="failed" stackId="jobs" fill="var(--color-failed)" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ChartContainer>
  </div>;
}
