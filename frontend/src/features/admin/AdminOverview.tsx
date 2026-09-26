import React from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Coins } from "lucide-react";

import { adminOverview, type AdminOverview as Overview } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { RangePicker, useStatRange } from "@/components/layout/RangePicker";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { gotoSettings } from "@/lib/deepLink";
import { formatCosts, microsIn } from "@/lib/money";
import { AdminActivityChart } from "./AdminActivityChart";

const CARD = "grid min-w-0 content-start gap-4 rounded-lg border border-border bg-panel p-5";
const CARD_TITLE = "m-0 text-ui-sm font-semibold text-foreground";

/**
 * 概览:顶上**一个**范围控件,下面四个读数、两张图。
 *
 * 范围管哪几块要写在明面上:任务活动和按人花费跟着它走,账户、工作区、素材是当前总数。所以
 * 跟着范围走的每一块,标题里都带着「近 N 天」—— 不必回头去找那个控件才知道这个数算的是多久。
 */
export function AdminOverview() {
  const t = useI18n();
  const { locale } = usePreferences();
  const [days, setDays] = useStatRange("admin-range");
  const overview = useQuery({
    queryKey: ["admin-overview", days],
    queryFn: () => adminOverview(days),
    // 换范围时先留着上一份,不让整页闪回骨架。
    placeholderData: keepPreviousData,
  });
  const stats = overview.data;
  // 「近 N 天」取**这份数据自己的**窗口,不取控件上的值:换范围时新数据还没到、先留着旧的那一刻,
  // 标题要说的是图上画的那段时间。
  const lastDays = t("statLastNDays").replace("{n}", String(stats?.window_days ?? days));

  const jobs = stats?.jobs_by_day ?? [];
  const jobsTotal = jobs.reduce((sum, point) => sum + point.total, 0);
  const jobsFailed = jobs.reduce((sum, point) => sum + point.failed, 0);

  return (
    // 范围、读数、图三块挨得近一些(gap-5):它们是同一件事的三层,不是三个分开的节。
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5">
      <div data-admin-section="range" className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <RangePicker days={days} onChange={setDays} />
        <p className="m-0 text-ui-xs text-muted-foreground">{t("adminRangeScope")}</p>
      </div>

      <section data-admin-section="stats" aria-label={t("adminTabOverview")} className="@container/stats grid min-w-0">
        <div className="grid grid-cols-2 gap-3 @min-[760px]/stats:grid-cols-4">
          <StatTile loading={overview.isPending} label={t("adminStatUsers")} value={stats?.users} hint={stats && t("adminStatActive").replace("{n}", String(stats.active_users_7d))} />
          <StatTile loading={overview.isPending} label={t("adminStatWorkspaces")} value={stats?.workspaces} />
          <StatTile loading={overview.isPending} label={t("adminStatAssets")} value={stats?.assets} />
          <StatTile
            loading={overview.isPending}
            label={t("adminStatSpend")}
            value={stats && (formatCosts(stats.costs, locale) || "0")}
            hint={lastDays}
          />
        </div>
      </section>

      <div className="@container/charts grid min-w-0">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 @min-[900px]/charts:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <section data-admin-section="activity" aria-labelledby="admin-activity-title" className={CARD}>
            <header className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2 id="admin-activity-title" className={CARD_TITLE}>
                {t("adminJobsTitle")} <span className="font-normal text-muted-foreground">· {lastDays}</span>
              </h2>
              {stats && jobsTotal > 0 && (
                <span className="text-ui-xs tabular-nums text-muted-foreground">
                  {t("adminJobsSummary").replace("{total}", String(jobsTotal)).replace("{failed}", String(jobsFailed))}
                </span>
              )}
            </header>
            <AdminActivityChart
              points={jobs}
              loading={overview.isPending}
              error={overview.isError}
              onRetry={() => void overview.refetch()}
            />
          </section>
          <section data-admin-section="spend" aria-labelledby="admin-spend-title" className={CARD}>
            <header className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2 id="admin-spend-title" className={CARD_TITLE}>
                {t("adminSpendTitle")} <span className="font-normal text-muted-foreground">· {lastDays}</span>
              </h2>
            </header>
            <SpendByPerson loading={overview.isPending} stats={stats} />
          </section>
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, hint, loading }: { label: string; value?: number | string; hint?: string; loading: boolean }) {
  return (
    <div data-stat className="grid min-w-0 content-start gap-2 rounded-lg border border-border bg-panel px-5 py-4">
      <span className="truncate text-ui-xs text-muted-foreground">{label}</span>
      {loading ? (
        <Skeleton className="h-8 w-20" />
      ) : (
        // 花费可能是一串钱(「CN¥32.45 + $4.50」)—— 窄的时候**折行**,不截断:截掉的那半正是另一种币。
        <strong className="text-2xl font-semibold leading-8 tabular-nums [overflow-wrap:anywhere]">
          {typeof value === "number" ? value.toLocaleString() : (value ?? "—")}
        </strong>
      )}
      <span className="min-h-4 truncate text-ui-xs leading-4 text-muted-foreground">{hint}</span>
    </div>
  );
}

/**
 * 花销**按人分**:一个总数说明不了任何该做的决定,而按人分的这一列直接指向要谈的那个人。
 *
 * 条形只能按一种钱量:取这台部署的主要币种(后端把它排在 costs 第一笔,也按它给人排序)。
 * 其他币种的钱照原样写在旁边 —— 不换算、不相加。
 */
function SpendByPerson({ stats, loading }: { stats?: Overview; loading: boolean }) {
  const t = useI18n();
  const { locale } = usePreferences();
  if (loading) {
    return (
      <div className="grid gap-4">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-9 w-full" />
        ))}
      </div>
    );
  }
  const spend = (stats?.spend_by_user ?? []).filter((row) => (row.costs ?? []).some((cost) => cost.micros > 0));
  if (spend.length === 0) {
    return (
      <EmptyState
        size="compact"
        icon={<Coins size={15} />}
        title={t("adminNoSpendTitle")}
        body={t("adminNoSpend")}
        action={
          <Button variant="outline" size="xs" onClick={() => gotoSettings("provider-pricing")}>
            {t("homeChartUsageConfigurePricing")}
          </Button>
        }
      />
    );
  }
  const primaryCurrency = stats?.costs?.[0]?.currency ?? "";
  const primaryMax = Math.max(0, ...spend.map((row) => microsIn(row.costs, primaryCurrency)));
  return (
    <div className="grid gap-4">
      <ul className="m-0 grid list-none gap-3.5 p-0">
        {spend.map((row) => (
          <li key={row.user_id || "unknown"} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-1.5 text-ui-sm">
            <span className="min-w-0 truncate">{row.username || t("adminNoOwner")}</span>
            {/* 金额**不设固定宽、不换行**:w-24 曾装不下「0.0007 USD · 6」,调用次数被挤到第二行。 */}
            <span className="whitespace-nowrap text-right text-ui-xs tabular-nums text-muted-foreground">
              {formatCosts(row.costs, locale)} · {row.calls}
            </span>
            <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-secondary">
              <span
                className="block h-full rounded-full bg-[var(--chart-image)]"
                style={{ width: `${Math.max(2, (microsIn(row.costs, primaryCurrency) / (primaryMax || 1)) * 100)}%` }}
              />
            </span>
          </li>
        ))}
      </ul>
      {(stats?.costs ?? []).length > 1 && (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
          {t("adminSpendCurrencyHint")
            .replace("{currency}", primaryCurrency)
            .replace("{total}", formatCosts(stats?.costs, locale))}
        </p>
      )}
    </div>
  );
}
