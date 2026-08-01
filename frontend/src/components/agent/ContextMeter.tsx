import React from "react";
import { Loader2, Scissors } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
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

/** 与 sidecar 的触发阈值一致(compaction.ts 的 COMPACT_RATIO)。到这条线就该提示了。 */
const WARN_RATIO = 0.8;

export interface ContextInfo {
  tokens: number;
  window: number;
}

function formatTokens(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(value);
}

export function ContextMeter({
  context,
  onCompact,
  compacting,
  className,
}: {
  context: ContextInfo | null | undefined;
  onCompact?: () => void;
  compacting?: boolean;
  className?: string;
}) {
  const t = useI18n();
  // 窗口未知时整条不显示。画一个没有分母的进度条只会让人误读成"快满了"。
  if (!context || !context.window || context.window <= 0) return null;

  const ratio = Math.min(1, context.tokens / context.window);
  const pct = Math.round(ratio * 100);
  const warn = ratio >= WARN_RATIO;

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <div
        className="h-1 w-16 overflow-hidden rounded-full bg-field"
        title={`${context.tokens.toLocaleString()} / ${context.window.toLocaleString()}`}
      >
        <div
          className={cn("h-full rounded-full transition-[width]", warn ? "bg-destructive" : "bg-primary")}
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
      <span className={cn("timecode shrink-0 text-[10.5px]", warn ? "text-destructive" : "text-muted-foreground")}>
        {formatTokens(context.tokens)}/{formatTokens(context.window)}
      </span>
      {onCompact && (
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          disabled={compacting}
          aria-label={t("agentCompactNow")}
          title={t("agentCompactNow")}
          onClick={onCompact}
        >
          {compacting ? <Loader2 size={11} className="animate-spin" /> : <Scissors size={11} />}
        </Button>
      )}
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
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Scissors size={11} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">
          {t("agentCompacted")
            .replace("{n}", String(info.droppedMessages))
            .replace("{saved}", formatTokens(saved))}
        </span>
        {info.summary && (
          <button
            type="button"
            className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? t("collapse") : t("expand")}
          </button>
        )}
      </div>
      {open && info.summary && (
        <p className="m-0 whitespace-pre-wrap text-[11.5px] leading-[1.6] text-foreground">{info.summary}</p>
      )}
    </div>
  );
}
