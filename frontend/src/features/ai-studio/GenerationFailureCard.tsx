import React from "react";
import { Check, CircleAlert, CircleStop, Copy, Lightbulb, RotateCcw, RotateCw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * 记录流里「没交回产出」的那一张卡的壳:已停止、生成失败共用。和在跑的占位、结果画廊是一家人 —— 同一个宽度(最宽 560px)、同样的
 * 圆角和留白、中性的面板底;**状态只靠一枚图标和一个短标题的颜色说**,正文是正常的前景色。此前失败卡整块粉红、正文全是红字,
 * 一条失败在会话里比它上面的成图还扎眼(维护者:「太丑」)。
 */
function NoOutputCard({
  icon,
  title,
  titleClassName,
  children,
  ...rest
}: {
  icon: React.ReactNode;
  title: string;
  titleClassName?: string;
  children?: React.ReactNode;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "title">) {
  const titleId = React.useId();
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className="grid w-[min(560px,100%)] min-w-0 gap-2 rounded-lg border border-border bg-secondary/40 px-3 py-2.5"
      {...rest}
    >
      <div className="flex min-w-0 items-start gap-2">
        <span aria-hidden className="mt-0.5 shrink-0">{icon}</span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <strong id={titleId} className={cn("text-ui-sm leading-[1.35]", titleClassName ?? "text-foreground")}>{title}</strong>
          {children}
        </div>
      </div>
    </div>
  );
}

/** 停下的那一条:不是失败,一枚灰色的停止图标,说一句没有产出。 */
export function GenerationStoppedCard() {
  const t = useI18n();
  return (
    <NoOutputCard icon={<CircleStop size={14} className="text-muted-foreground" />} title={t("genStopped")} data-generation-stopped="">
      <span className="text-ui-sm leading-[1.55] text-muted-foreground">{t("genStoppedBody")}</span>
    </NoOutputCard>
  );
}

/** 一颗失败卡上的动作:再来一次、重新取回。`run` 不给就不摆。 */
export type FailureAction = { run: () => void; pending?: boolean };

/**
 * 跑挂了的那一条。
 *
 * - **一句人话**(`summary`,后端的 `error_summary`,和画板格子同一个来源):不再带「「连接名」生成失败:」—— 连接和模型在脚注里,
 *   「生成失败」是标题。ComfyUI 的节点错误说成「ComfyUI 执行到「KSampler」这一步出错」,原话进详情。
 * - **认得出的原因**(`hint`,插件或后端的失败归类给的):该去哪修,摆在那句话下面。
 * - **动作按失败的性质给**,排一行小按钮:「再来一次」(同样的模型和参数重新提交)、「重新取回」(只在远端可能已经做完、是我们没拿到时,
 *   后端说了算)、记着的模型用不了时「去工作流库升级」(`upgrade`)、没有详情时「复制错误」。
 * - **原文收进默认折起的「详情」**(等宽字,复制在里面);原文和那句话说的是同一件事时后端不给(`detail` 是 null),也就不摆。
 */
export function GenerationFailureCard({
  summary: said,
  detail,
  hint,
  copyText,
  repeat,
  retrieve,
  upgrade,
}: {
  summary: string;
  /** 原文:比那一句多出信息时才有 */
  detail: string | null;
  hint: string | null;
  /** 「复制错误」复制的那一段(记录上存的整句失败原因,报问题时最有用) */
  copyText: string;
  repeat?: FailureAction;
  retrieve?: FailureAction;
  /** 「去工作流库升级」那一颗(记着的模型用不了、修法是升级时由调用方给) */
  upgrade?: React.ReactNode;
}) {
  const t = useI18n();
  const summary = said.trim() || t("genFailed");
  const copyable = (copyText || detail || summary).trim();
  return (
    <NoOutputCard
      icon={<CircleAlert size={14} className="text-destructive" />}
      title={t("generationFailedTitle")}
      titleClassName="text-destructive"
      data-generation-failed=""
    >
      <p className="m-0 [overflow-wrap:anywhere] text-ui-sm leading-[1.55] text-foreground" data-failure-summary="">{summary}</p>
      {hint ? (
        <p className="m-0 flex min-w-0 items-start gap-1.5 text-ui-sm leading-[1.55] text-muted-foreground" data-failure-hint="">
          <Lightbulb size={13} aria-hidden className="mt-[3px] shrink-0 text-warning" />
          <span className="min-w-0 [overflow-wrap:anywhere]">{hint}</span>
        </p>
      ) : null}
      {repeat || retrieve || upgrade || !detail ? (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 pt-1" data-failure-actions="">
          {repeat ? (
            <Hint label={t("genRepeatHint")}>
              <Button type="button" variant="outline" size="xs" loading={repeat.pending} onClick={repeat.run} data-failure-repeat="">
                <RotateCw size={12} />
                {t("genRepeat")}
              </Button>
            </Hint>
          ) : null}
          {retrieve ? (
            <Hint label={t("genRetrieveHint")}>
              <Button type="button" variant="outline" size="xs" loading={retrieve.pending} onClick={retrieve.run} data-failure-retrieve="">
                <RotateCcw size={12} />
                {t("genRetrieve")}
              </Button>
            </Hint>
          ) : null}
          {upgrade}
          {!detail && copyable ? <CopyButton text={copyable} label={t("genCopyError")} /> : null}
        </div>
      ) : null}
      {detail ? (
        <details className="group/details min-w-0 pt-0.5" data-failure-detail="">
          <summary className="w-fit cursor-pointer list-none rounded text-ui-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring after:ml-1 after:inline-block after:transition-transform after:content-['›'] group-open/details:after:rotate-90 [&::-webkit-details-marker]:hidden">
            {t("genFailureDetail")}
          </summary>
          <div className="mt-1.5 grid min-w-0 gap-1 rounded-md border border-border bg-background/60 p-2">
            <pre className="m-0 max-h-48 min-w-0 overflow-auto whitespace-pre-wrap break-words font-mono text-ui-xs leading-normal text-muted-foreground">
              {detail}
            </pre>
            <CopyButton text={copyable} label={t("genCopyError")} className="justify-self-end" />
          </div>
        </details>
      ) : null}
    </NoOutputCard>
  );
}

function CopyButton({ text, label, className }: { text: string; label: string; className?: string }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <Button type="button" variant="ghost" size="xs" className={cn("text-muted-foreground", className)} onClick={copy}
            data-failure-copy="">
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? t("copied") : label}
    </Button>
  );
}
