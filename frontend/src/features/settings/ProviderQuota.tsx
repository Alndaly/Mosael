import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Gauge, Loader2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type QuotaOut = components["schemas"]["ProviderQuotaOut"];
type Metric = components["schemas"]["ProviderQuotaMetricOut"];

/**
 * 订阅额度:点一下查一次。
 *
 * **手动而不是自动**:这些端点没有一个是官方承诺的公开接口(Anthropic 的 oauth/usage、
 * Codex 的 codex/usage 都是各自 CLI 内部在用),后台轮询既容易撞限流,也会在对方改接口后
 * 变成一直在失败的定时任务。
 *
 * **不压成一个数字**:各家的额度类型和周期对不齐 —— 滚动窗口的利用率百分比、美元余额、
 * 周期用量,分母存在与否都不一样。所以每条指标自带 kind 和周期,这里按 kind 分别渲染:
 * 有分母的画进度条,没分母的只报数,不去编一个不存在的上限。
 */

/** 秒 → 「5 小时」「7 天」。窗口长度是各家响应自己给的,不是我们假设的。 */
function windowLabel(seconds: number | null | undefined, t: ReturnType<typeof useI18n>): string {
  if (!seconds) return "";
  if (seconds % 86400 === 0) return t("quotaWindowDays").replace("{n}", String(seconds / 86400));
  if (seconds % 3600 === 0) return t("quotaWindowHours").replace("{n}", String(seconds / 3600));
  return t("quotaWindowMinutes").replace("{n}", String(Math.round(seconds / 60)));
}

/** 把没有词条的键名整理成人能读的样子。window_0 → 窗口配额 1,copilot_chat → chat。 */
function humanizeKey(key: string, t: ReturnType<typeof useI18n>): string {
  const window = /^window_(\d+)$/.exec(key);
  if (window) return t("quotaMetric_window").replace("{n}", String(Number(window[1]) + 1));
  return key.replace(/^copilot_/, "").replace(/_/g, " ");
}

/** 计划名各家写法不一(Kimi 回 LEVEL_INTERMEDIATE)。去掉前缀、拆下划线,别把枚举名直接摆出来。 */
function humanizePlan(plan: string): string {
  return plan.replace(/^(LEVEL|PLAN|TIER)_/i, "").replace(/_/g, " ").toLowerCase();
}

function MetricRow({ metric }: { metric: Metric }) {
  const t = useI18n();
  // 各家的键名各不相同,i18n 表不可能穷举(Kimi 的窗口是 window_0/window_1,Copilot 是
  // copilot_<配额名>)。有对应词条就用,没有就把键名整理成人能读的样子 —— 直接回退到裸键
  // 会让弹窗里冒出 window_0、total 这种只有写代码的人看得懂的东西。
  const label = t(`quotaMetric_${metric.key}` as never) || humanizeKey(metric.key, t);
  const window = windowLabel(metric.window_seconds, t);

  if (metric.kind === "percent") {
    const pct = Math.max(0, Math.min(100, metric.used_percent ?? 0));
    return (
      <div className="grid gap-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-ui-xs text-foreground">
            {label}
            {window && <span className="text-muted-foreground"> · {window}</span>}
          </span>
          <span className="timecode shrink-0 text-ui-xs text-muted-foreground">{pct.toFixed(0)}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-field">
          {/* 90% 起转红:额度这种东西,"快没了"要比"还有多少"更显眼。 */}
          <div
            className={cn("h-full rounded-full transition-[width]", pct >= 90 ? "bg-destructive" : "bg-primary")}
            style={{ width: `${pct}%` }}
          />
        </div>
        {metric.resets_at && (
          <span className="text-ui-2xs text-muted-foreground">
            {t("quotaResetsAt").replace("{t}", new Date(metric.resets_at).toLocaleString())}
          </span>
        )}
      </div>
    );
  }

  // 余额型:limit 为空 = 对方不限额,这时只报已用量。编一个分母出来会让进度条永远接近满。
  const amount = (value: number) => (metric.unit === "USD" ? `$${value.toFixed(2)}` : value.toLocaleString());
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="truncate text-ui-xs text-foreground">
        {label}
        {window && <span className="text-muted-foreground"> · {window}</span>}
      </span>
      <span className="timecode shrink-0 text-ui-xs text-muted-foreground">
        {metric.used != null ? amount(metric.used) : "—"}
        {metric.limit != null ? ` / ${amount(metric.limit)}` : metric.unlimited ? ` · ${t("quotaUnlimited")}` : ""}
      </span>
    </div>
  );
}

export function ProviderQuota({ profileId }: { profileId: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);

  const quota = useQuery({
    queryKey: ["provider-quota", profileId],
    queryFn: () => api<QuotaOut>(`/api/settings/providers/${profileId}/quota`, { method: "POST" }),
    // 只在气泡打开时查一次。这些端点都不是官方承诺的公开接口,自动轮询既容易撞限流,
    // 也会在对方改接口后变成后台里一直在失败的任务。
    enabled: open,
    staleTime: 60_000,
    retry: false,
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/* 与授权/登出/编辑/开关/删除同列的图标钮:额度是这一行的又一个动作,
            单独占一行的胶囊按钮会把每张卡撑高一截,行与行的节奏也就散了。 */}
        <Button variant="ghost" size="icon" aria-label={t("quotaFetch")} title={t("quotaFetch")}>
          <Gauge size={13} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[280px] p-2.5">
        {quota.isFetching ? (
          <span className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            {t("quotaLoading")}
          </span>
        ) : quota.isError ? (
          <div className="grid gap-1.5">
            <span className="text-ui-xs text-destructive">{String(quota.error)}</span>
            <Button variant="outline" size="sm" className="w-fit" onClick={() => void quota.refetch()}>
              {t("quotaRefresh")}
            </Button>
          </div>
        ) : quota.data?.error ? (
          // 「这次没查成」要能重试;「这家查不了」不该给重试按钮 —— 见下一分支。
          <div className="grid gap-1.5">
            <span className="text-ui-xs text-destructive">{quota.data.error}</span>
            <Button variant="outline" size="sm" className="w-fit" onClick={() => void quota.refetch()}>
              {t("quotaRefresh")}
            </Button>
          </div>
        ) : (
          <div className="grid gap-2">
            {/* 计划名与「重新查询」同处一行:标题行右侧本来就是放操作的地方,而把刷新挂在
                列表末尾会让它跟最后一条指标黏在一起,像是那一条的附属。 */}
            <div className="flex items-center justify-between gap-2 border-b border-border pb-1.5">
              <span className="min-w-0 truncate text-ui-2xs uppercase tracking-wide text-muted-foreground">
                {quota.data?.plan ? humanizePlan(quota.data.plan) : t("agentContextTitle")}
              </span>
              <button
                type="button"
                className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-ui-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                onClick={() => void quota.refetch()}
              >
                {t("quotaRefresh")}
              </button>
            </div>
            {(quota.data?.metrics ?? []).map((metric) => (
              <MetricRow key={metric.key} metric={metric} />
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
