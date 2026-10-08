import React from "react";
import { Check, ChevronDown, CircleAlert, CircleStop, Copy, RotateCcw, RotateCw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * 记录流里「没交回产出」的那一张卡的壳:已停止、生成失败共用,和在跑的占位、结果画廊同一个宽度(最宽 560px,窄栏里铺满)。
 *
 * **一张卡四层,从上往下一层比一层次要**(维护者:「错误卡的排版也得重构一遍」—— 此前上下堆着红标题、正文、灯泡提示、按钮行、
 * 「详情⌄」五种排印,像几张便签叠在一起):
 *
 * 1. 卡头一行:状态(一枚图标 + 短标题,只有它带状态色)在左,这一条的元信息(模型 · 用时 · 费用 · 时间)在右 —— 此前元信息在卡外
 *    另起一行、时间飘在右上角,看不出是谁的;
 * 2. 出了什么事:一句话,卡里最醒目的字;
 * 3. 为什么、怎么修(认得出时):收在一块内嵌的面板里,原因一句、步骤一步一行,命令单独一块等宽字带复制;
 * 4. 动作一行:左边是该点的(再来一次、重新取回、去升级),右边是「详情」开关和复制图标;详情展开在这一行下面,是一块等宽字。
 *
 * 窄栏里不再按图标留一道缩进(此前正文缩在图标右边、提示又缩在灯泡右边,760 宽时一句提示折成七八行):正文贴着卡的左边;
 * 卡头的元信息放不下就换到下一行,原因 / 怎么修的标签从左边一栏改成摞在上面。
 */
function NoOutputCard({
  icon,
  title,
  titleClassName,
  meta,
  children,
  ...rest
}: {
  icon: React.ReactNode;
  title: string;
  titleClassName?: string;
  /** 卡头右边:这一条用的模型、用时、费用、时间(调用方摆好) */
  meta?: React.ReactNode;
  children?: React.ReactNode;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "title">) {
  const titleId = React.useId();
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className="@container/no-output grid w-[min(560px,100%)] min-w-0 gap-2.5 rounded-lg border border-border bg-secondary/40 px-3.5 py-3"
      {...rest}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1" data-no-output-head="">
        <span className="flex shrink-0 items-center gap-1.5">
          <span aria-hidden className="flex">{icon}</span>
          <strong id={titleId} className={cn("text-ui-xs font-semibold", titleClassName ?? "text-foreground")}>{title}</strong>
        </span>
        {/* 宽的时候元信息靠右和标题同一行;卡窄于 440px 时整块换到标题下面、靠左(不然长的那几条一半靠左一半靠右) */}
        {meta ? (
          <div className="ml-auto min-w-0 @max-[439px]/no-output:ml-0 @max-[439px]/no-output:basis-full" data-no-output-meta="">
            {meta}
          </div>
        ) : null}
      </div>
      {children}
    </div>
  );
}

/** 停下的那一条:不是失败,一枚灰色的停止图标,说一句没有产出。 */
export function GenerationStoppedCard({ meta }: { meta?: React.ReactNode }) {
  const t = useI18n();
  return (
    <NoOutputCard
      icon={<CircleStop size={13} className="text-muted-foreground" />}
      title={t("genStopped")}
      titleClassName="text-muted-foreground"
      meta={meta}
      data-generation-stopped=""
    >
      <p className="m-0 text-ui-sm leading-[1.55] text-foreground">{t("genStoppedBody")}</p>
    </NoOutputCard>
  );
}

/** 一颗失败卡上的动作:再来一次、重新取回。`run` 不给就不摆。 */
export type FailureAction = { run: () => void; pending?: boolean };

/** 认得出的失败:为什么(一句)、怎么修(一步一句,要敲的命令单独一格)—— 后端 `error_hint`,插件说的。 */
export type FailureFix = {
  cause?: string | null;
  steps?: readonly { readonly text: string; readonly command?: string | null }[];
};

/**
 * 跑挂了的那一条。
 *
 * - **一句人话**(`summary`,后端的 `error_summary`,和画板格子同一个来源):不带「「连接名」生成失败:」—— 连接和模型在卡头右边,
 *   「生成失败」是卡头的标题。ComfyUI 的节点错误说成「ComfyUI 执行到「KSampler」这一步出错」,原话进详情。
 * - **为什么、怎么修**(`fix`,后端的 `error_hint`):插件按「原因 + 步骤 + 命令」分着交,前端照格子摆,不解析句子。
 * - **动作按失败的性质给**:「再来一次」(同样的模型和参数重新提交)、「重新取回」(只在远端可能已经做完、是我们没拿到时,后端说了算)、
 *   记着的模型用不了时「去工作流库升级」(`upgrade`);复制错误一直在右边。
 * - **原文**(`detail`)比那一句多出信息时才有「详情」开关;展开是一块等宽字。
 */
export function GenerationFailureCard({
  summary: said,
  detail,
  fix,
  copyText,
  meta,
  repeat,
  retrieve,
  upgrade,
}: {
  summary: string;
  /** 原文:比那一句多出信息时才有 */
  detail: string | null;
  fix: FailureFix | null;
  /** 「复制错误」复制的那一段(记录上存的整句失败原因,报问题时最有用) */
  copyText: string;
  meta?: React.ReactNode;
  repeat?: FailureAction;
  retrieve?: FailureAction;
  /** 「去工作流库升级」那一颗(记着的模型用不了、修法是升级时由调用方给) */
  upgrade?: React.ReactNode;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const detailId = React.useId();
  const summary = said.trim() || t("genFailed");
  const copyable = (copyText || detail || summary).trim();
  const steps = (fix?.steps ?? []).filter((step) => step.text.trim() || step.command?.trim());
  const cause = fix?.cause?.trim() ?? "";
  return (
    <NoOutputCard
      icon={<CircleAlert size={13} className="text-destructive" />}
      title={t("generationFailedTitle")}
      titleClassName="text-destructive"
      meta={meta}
      data-generation-failed=""
    >
      <p className="m-0 text-ui-md font-medium leading-[1.5] text-foreground [overflow-wrap:anywhere]" data-failure-summary="">
        {summary}
      </p>
      {cause || steps.length ? (
        <dl
          className="m-0 grid min-w-0 gap-2.5 rounded-md border border-border bg-background/70 px-3 py-2.5 text-ui-sm leading-[1.55]"
          data-failure-fix=""
        >
          {cause ? (
            <FixRow label={t("genFailureCause")}>
              <span className="text-foreground [overflow-wrap:anywhere]" data-failure-cause="">{cause}</span>
            </FixRow>
          ) : null}
          {steps.length ? (
            <FixRow label={t("genFailureFix")}>
              {steps.length === 1 ? (
                <FixStep step={steps[0]} />
              ) : (
                <ol className="m-0 grid list-none gap-2 p-0" data-failure-steps="">
                  {steps.map((step, index) => (
                    <li key={index} className="grid min-w-0 grid-cols-[1.1rem_minmax(0,1fr)] items-start">
                      <span aria-hidden className="tabular-nums text-muted-foreground">{index + 1}.</span>
                      <FixStep step={step} />
                    </li>
                  ))}
                </ol>
              )}
            </FixRow>
          ) : null}
        </dl>
      ) : null}
      <div className="flex min-w-0 flex-wrap items-center gap-1.5" data-failure-actions="">
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
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {detail ? (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="gap-1 px-2 text-muted-foreground"
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpen((value) => !value)}
              data-failure-detail-toggle=""
            >
              {t("genFailureDetail")}
              <ChevronDown size={12} aria-hidden className={cn("transition-transform duration-150", open && "rotate-180")} />
            </Button>
          ) : null}
          {copyable ? <CopyIconButton text={copyable} label={t("genCopyError")} data-failure-copy="" /> : null}
        </div>
      </div>
      {detail ? (
        <pre
          id={detailId}
          hidden={!open}
          className="m-0 max-h-48 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-background/70 px-2.5 py-2 font-mono text-ui-xs leading-normal text-muted-foreground [font-variant-ligatures:none]"
          data-failure-detail=""
        >
          {detail}
        </pre>
      ) : null}
    </NoOutputCard>
  );
}

/** 「原因」「怎么修」一行:宽的时候标签在左边一栏(两行的标签对齐),窄的时候摞在上面。 */
function FixRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-1 @min-[440px]/no-output:grid-cols-[5rem_minmax(0,1fr)] @min-[440px]/no-output:gap-3">
      <dt className="text-ui-xs font-medium leading-[1.8] text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0">{children}</dd>
    </div>
  );
}

function FixStep({ step }: { step: { text: string; command?: string | null } }) {
  const t = useI18n();
  const command = step.command?.trim() ?? "";
  return (
    <div className="grid min-w-0 gap-1.5">
      {step.text.trim() ? <span className="text-foreground [overflow-wrap:anywhere]">{step.text}</span> : null}
      {command ? (
        //: 命令单独一块等宽字、带复制:照抄去终端里敲的东西,不该埋在一句话中间。关掉连字 —— 等宽字体会把 `>=` 画成「≥」,
        //: 照着敲的人会敲错
        <div className="flex min-w-0 items-start gap-1 rounded-md border border-border bg-secondary/70 py-0.5 pl-2.5 pr-0.5" data-failure-command="">
          <code className="min-w-0 flex-1 whitespace-pre-wrap py-[5px] font-mono text-ui-xs leading-[1.5] text-foreground [font-variant-ligatures:none] [overflow-wrap:anywhere]">
            {command}
          </code>
          <CopyIconButton text={command} label={t("genCopyCommand")} />
        </div>
      ) : null}
    </div>
  );
}

function CopyIconButton({ text, label, ...rest }: { text: string; label: string } & { [key: `data-${string}`]: string }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <IconButton label={copied ? t("copied") : label} size="icon-xs" className="shrink-0 text-muted-foreground" onClick={copy} {...rest}>
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </IconButton>
  );
}
