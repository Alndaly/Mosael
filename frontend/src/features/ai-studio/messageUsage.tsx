import React from "react";
import { Check, Copy } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 一条助手回复的用量/计费页脚——AI Studio 对话页与工作流助手共用,避免两处漂移。
 * 计费事件按 agent_message_id 归到各自消息(见各页 usageByMessage),这里做汇总与展示。
 */

export type AgentUsageEvent = {
  id: string;
  agent_message_id: string | null;
  provider: string;
  model: string;
  capability: string;
  operation: string;
  status: string;
  duration_seconds: number | null;
  units: Record<string, unknown>;
  cost_micros: number | null;
  currency: string;
  cost_confidence: string;
};

function numberUnit(value: unknown): number | null {
  if (typeof value === "boolean") return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function quantityForUnit(units: Record<string, unknown>, unit: "token" | "input_token" | "output_token"): number {
  const aliases = {
    token: ["token", "tokens", "total_token", "total_tokens"],
    input_token: ["input_token", "input_tokens", "prompt_tokens", "input_characters"],
    output_token: ["output_token", "output_tokens", "completion_tokens", "output_characters"],
  } satisfies Record<typeof unit, string[]>;
  for (const key of aliases[unit]) {
    const value = numberUnit(units[key]);
    if (value != null) return value;
  }
  if (unit === "token") {
    const input = quantityForUnit(units, "input_token");
    const output = quantityForUnit(units, "output_token");
    return input + output;
  }
  return 0;
}

export function summarizeMessageUsage(events: AgentUsageEvent[]) {
  let inputTokens = 0;
  let outputTokens = 0;
  let totalTokens = 0;
  let durationSeconds = 0;
  let hasDuration = false;
  let unknownCostEvents = 0;
  const costByCurrency = new Map<string, number>();

  for (const event of events) {
    const units = event.units ?? {};
    const input = quantityForUnit(units, "input_token");
    const output = quantityForUnit(units, "output_token");
    const total = Math.max(quantityForUnit(units, "token"), input + output);
    inputTokens += input;
    outputTokens += output;
    totalTokens += total;
    if (typeof event.duration_seconds === "number") {
      durationSeconds += event.duration_seconds;
      hasDuration = true;
    }
    if (typeof event.cost_micros === "number") {
      const currency = event.currency || "USD";
      costByCurrency.set(currency, (costByCurrency.get(currency) ?? 0) + event.cost_micros);
    } else {
      unknownCostEvents += 1;
    }
  }

  return {
    inputTokens: Math.round(inputTokens),
    outputTokens: Math.round(outputTokens),
    totalTokens: Math.round(totalTokens),
    durationSeconds: hasDuration ? durationSeconds : null,
    costByCurrency,
    unknownCostEvents,
  };
}

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value);
}

export function formatCostMicros(currency: string, micros: number): string {
  const amount = micros / 1_000_000;
  const symbol = currency === "USD" ? "$" : currency === "CNY" ? "¥" : "";
  const precision = amount > 0 && amount < 0.01 ? 6 : 4;
  const value = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: amount === 0 ? 0 : 2,
    maximumFractionDigits: precision,
  }).format(amount);
  return symbol ? `${symbol}${value}` : `${value} ${currency}`;
}

function formatUsageCost(events: ReturnType<typeof summarizeMessageUsage>, t: ReturnType<typeof useI18n>): string | null {
  const known = [...events.costByCurrency.entries()].filter(([, value]) => value >= 0);
  if (known.length > 0) {
    return t("usageCost").replace(
      "{cost}",
      known.map(([currency, micros]) => formatCostMicros(currency, micros)).join(" + "),
    );
  }
  return events.unknownCostEvents > 0 ? t("usageCostUnknown") : null;
}

/** 助手回复页脚:复制 + 耗时 + tokens + 计费。durationOverride 用消息 payload 里的耗时兜底。 */
export function MessageUsageFooter({
  content,
  usageEvents,
  durationOverride,
  className,
}: {
  content: string;
  usageEvents: AgentUsageEvent[];
  durationOverride?: number | null;
  className?: string;
}) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const usage = summarizeMessageUsage(usageEvents);
  const duration = durationOverride ?? usage.durationSeconds;
  const tokenLabel = usage.totalTokens > 0 ? t("usageTokens").replace("{n}", formatTokenCount(usage.totalTokens)) : null;
  const tokenTitle =
    usage.inputTokens > 0 || usage.outputTokens > 0
      ? `${t("homeLegendInputTokens")} ${formatTokenCount(usage.inputTokens)} · ${t("homeLegendOutputTokens")} ${formatTokenCount(usage.outputTokens)}`
      : undefined;
  const costLabel = formatUsageCost(usage, t);

  const copy = () => {
    void navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className={cn("mt-1.5 flex min-h-[18px] items-center gap-1.5", className)}>
      <button
        type="button"
        className="inline-flex cursor-pointer items-center gap-1 rounded-sm border-0 bg-transparent px-1.5 py-0.5 text-ui-xs text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground"
        title={t("copyMessage")}
        onClick={copy}
      >
        {copied ? <Check size={11} /> : <Copy size={11} />}
        {copied ? t("copied") : t("copyMessage")}
      </button>
      {typeof duration === "number" && (
        <span className="timecode text-ui-xs text-muted-foreground">
          {t("usageDuration").replace("{t}", formatElapsedSeconds(duration))}
        </span>
      )}
      {tokenLabel && (
        <span className="text-ui-xs text-muted-foreground" title={tokenTitle}>
          {tokenLabel}
        </span>
      )}
      {costLabel && <span className="text-ui-xs text-muted-foreground">{costLabel}</span>}
    </div>
  );
}
