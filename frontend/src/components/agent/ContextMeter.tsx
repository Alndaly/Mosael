import React from "react";
import { Loader2, Scissors } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * 上下文水位 + 手动整理入口。
 *
 * 之前完全没有:压缩是静默发生的,用户在第 50 条问「刚才那个方案叫什么」,模型看不到了,
 * 表现得像它自己忘了。有了这条水位,"快满了"是可预期的;配上对话流里的压缩标记,
 * "早期内容已经被整理走"也是可见的。
 *
 * **窗口按当前模型给**(后端从供应商目录取,随会话选定的模型变)。用一个全局常量会在
 * 8k 上下文的本地模型上显示成"还早得很",而它其实早就该压了。
 */

/** 与 sidecar 的触发阈值一致(compaction.ts 的 COMPACT_RATIO)。到这条线就该显眼了。 */
const WARN_RATIO = 0.8;

export interface ContextPart {
  kind: string;
  tokens: number;
}

export interface ContextInfo {
  tokens: number;
  window: number;
  /** 各分项之和 = window 时的实际占用。老响应没有这个字段,回落到 tokens。 */
  used?: number;
  parts?: ContextPart[];
}

/**
 * 分项的顺序与配色。**固定顺序**:同一段永远在同一个位置,水位变化时眼睛才追得住。
 *
 * 颜色只用 tokens.css 里真实存在的 `--chart-*`(dataviz 校验过的明暗两档)。编一个不存在的
 * 变量名不会报错,只会渲染成**透明** —— 第一版写了 `--chart-2/--chart-4`,于是占了 35% 的
 * 那两段在条上完全看不见,而图例里的色块也是空的。ContextMeter.dom.test 里有一条守着这个。
 *
 * `free` 用的是条本身的底色,所以不在这里给色 —— 它是"没被占"的那段,不是第四种内容。
 */
export const PART_COLORS: Record<string, string> = {
  messages: "bg-[var(--chart-ok)]",
  tools: "bg-[var(--chart-audio)]",
  system: "bg-[var(--chart-image)]",
};
const PART_ORDER = ["messages", "tools", "system", "free"] as const;

function formatTokens(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(value);
}

export function ContextMeter({
  context,
  compacting,
  className,
}: {
  context: ContextInfo | null | undefined;
  compacting?: boolean;
  className?: string;
}) {
  const t = useI18n();
  // 窗口未知时整条不显示:没有分母的进度条只会被读成"快满了"。
  if (!context || !context.window || context.window <= 0) return null;

  // **按实际占用算**,而不是按对话那部分:工具定义与系统提示每轮都要重发,一条消息都没有
  // 的会话也已经占掉了三成。用对话量当分子,水位会在开口前显示"剩余 100%",而它不是。
  const used = context.used ?? context.tokens;
  const ratio = Math.min(1, used / context.window);

  // 报**剩余**而不是已用:用户此刻在决定"还能不能接着问",剩余量是直接答案,
  // 已用量还要在脑子里做一次减法。Claude Code 的 "Context left" 是同一个道理。
  const left = Math.max(0, Math.round((1 - ratio) * 100));
  const warn = ratio >= WARN_RATIO;
  const parts = (context.parts ?? []).filter((part) => part.kind !== "free" && part.tokens > 0);

  const meter = (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className="flex h-1 w-10 overflow-hidden rounded-full bg-field">
        {parts.length > 0 && !warn ? (
          // 分段:同一条水位同时回答"满了多少"和"被什么占的"。过线之后整条转告警色 ——
          // 那一刻要说的是"快满了",分项让位。
          parts.map((part) => (
            <span
              key={part.kind}
              className={cn("block h-full transition-[width]", PART_COLORS[part.kind] ?? "bg-muted-foreground")}
              style={{ width: `${(part.tokens / context.window) * 100}%` }}
            />
          ))
        ) : (
          <span
            className={cn("block h-full rounded-full transition-[width]", warn ? "bg-destructive" : "bg-primary")}
            style={{ width: `${Math.max(2, Math.round(ratio * 100))}%` }}
          />
        )}
      </span>
      <span className={cn("timecode shrink-0 text-ui-2xs", warn ? "text-destructive" : "text-muted-foreground")}>
        {t("agentContextLeft").replace("{n}", String(left))}
      </span>
      {compacting && <Loader2 size={11} className="shrink-0 animate-spin text-muted-foreground" />}
    </span>
  );

  // 没有分项就没有可展开的东西 —— 给一个点开是空的浮层,比不给更像坏了。
  if (!context.parts || context.parts.length === 0) {
    return <span title={`${used.toLocaleString()} / ${context.window.toLocaleString()}`}>{meter}</span>;
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="cursor-pointer rounded border-0 bg-transparent p-0 text-left"
          aria-label={t("agentContextBreakdown")}
        >
          {meter}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[260px] p-2.5">
        <ContextBreakdown context={context} />
      </PopoverContent>
    </Popover>
  );
}

/**
 * 窗口被**什么**占满了。
 *
 * 单独一个百分比回答不了任何该做的决定:满了要清什么?清对话有用吗?这个应用里最大的一块
 * 常常**不是对话** —— 几十个工具的 JSON schema 每轮重发一遍。只给百分比,用户会去删对话,
 * 而那恰恰是最小的一块。
 */
export function ContextBreakdown({ context }: { context: ContextInfo }) {
  const t = useI18n();
  const byKind = new Map((context.parts ?? []).map((part) => [part.kind, part.tokens]));
  const rows = PART_ORDER.filter((kind) => (byKind.get(kind) ?? 0) > 0);

  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-ui-xs font-[620]">{t("agentContextBreakdown")}</span>
        <span className="timecode text-ui-2xs text-muted-foreground">
          {formatTokens(context.used ?? context.tokens)} / {formatTokens(context.window)}
        </span>
      </div>
      <ul className="m-0 grid list-none gap-1 p-0">
        {rows.map((kind) => {
          const tokens = byKind.get(kind) ?? 0;
          return (
            <li key={kind} className="flex items-center gap-1.5 text-ui-xs">
              <span
                className={cn(
                  "h-2 w-2 shrink-0 rounded-sm",
                  kind === "free" ? "border border-border bg-field" : PART_COLORS[kind] ?? "bg-muted-foreground",
                )}
              />
              <span className="min-w-0 flex-1 truncate">{t(`agentContextPart_${kind}`)}</span>
              <span className="timecode shrink-0 text-muted-foreground">
                {formatTokens(tokens)} · {Math.round((tokens / context.window) * 100)}%
              </span>
            </li>
          );
        })}
      </ul>
      <p className="m-0 text-ui-2xs leading-[1.5] text-muted-foreground">{t("agentContextFixedHint")}</p>
    </div>
  );
}

export interface CompactionInfo {
  droppedMessages: number;
  tokensBefore: number;
  tokensAfter: number;
  summary: string;
}

/**
 * 对话流里的压缩标记。**默认折叠但始终可见** —— 压缩本身必须被看见,而摘要正文平时是噪音。
 * 摘要为空(摘要那次调用失败,退回了截断)时不给展开:没有内容可看,一个点不开的三角
 * 比一个空面板更诚实。
 */
export function CompactionNotice({ info }: { info: CompactionInfo }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const saved = Math.max(0, info.tokensBefore - info.tokensAfter);

  return (
    <div className="grid gap-1 rounded-md border border-dashed border-border bg-panel-subtle px-2.5 py-1.5">
      <div className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
        <Scissors size={11} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          {t("agentCompacted")
            .replace("{n}", String(info.droppedMessages))
            .replace("{saved}", formatTokens(saved))}
        </span>
        {info.summary && (
          <button
            type="button"
            className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-ui-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? t("collapse") : t("expand")}
          </button>
        )}
      </div>
      {open && info.summary && (
        <p className="m-0 whitespace-pre-wrap text-ui-xs leading-[1.6] text-foreground">{info.summary}</p>
      )}
    </div>
  );
}
