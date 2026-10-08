import React from "react";
import { Check, ChevronDown, CircleAlert, CircleStop, Copy } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 一次失败(或停下)给人看的样子 —— 全应用只此一份:AI 工作台的记录流、智能体的工具调用和确认卡、画板格子、工作流的节点和
 * 整轮、任务中心、发布、导出、ComfyUI 工作台的运行与结果都走它(棘轮:design/failureDisplays.test.ts)。
 *
 * **四层,从上往下一层比一层次要**(维护者:「失败的那个卡片 UI 也进行彻底的重构排版」—— 此前各处各写一份:一行红字、一块粉红、
 * 原文头三行、一个灯泡加一大段话,有的连原因都没有):
 *
 * 1. 卡头一行:状态(一枚图标 + 短标题,只有它带状态色)在左,这一次的元信息(模型 · 用时 · 时间……)在右;
 * 2. 出了什么事:一句话(后端 `error_summary`,和别处同一个来源),卡里最醒目的字;
 * 3. 为什么、怎么修(后端 `error_hint`,认得出时才有):内嵌的一块面板,原因一句、步骤一步一行,命令单独一块等宽字带复制;
 * 4. 动作一行:左边是该点的(调用方给:再来一次、重试、去处理……),右边是「详情」开关和复制;详情展开是一块等宽字(后端
 *    `error_detail`,比那一句多出信息时才有)。
 *
 * **两档。** `full` 是一张卡(记录流、详情对话框、运行面板);`compact` 给放不下一张卡的地方(画板格子、工作流画布上的节点、
 * 列表里的一行):一枚图标、短标题、截断的那一句,其余(原因、怎么修、动作、原文、复制)收进点开的「详情」浮层 —— 格子不撑大,
 * 浮层里放得下能点的东西(悬停说明放不了按钮)。
 *
 * **没有 hint 的地方就只有一句话加详情**,不硬凑一块「原因 / 怎么修」。
 */

/** 认得出的失败:为什么(一句)、怎么修(一步一句,要敲的命令单独一格)—— 后端 `error_hint`,插件或后端的失败归类说的。 */
export type FailureFix = {
  cause?: string | null;
  steps?: readonly { readonly text: string; readonly command?: string | null }[];
};

/** 后端那份失败的几格:任务、生成记录、发布、定时运行、画板格子都是这个形状(见后端 domain/failure_summary)。 */
export type FailureSource = {
  error?: string | null;
  error_summary?: string | null;
  error_detail?: string | null;
  error_hint?: FailureFix | null;
};

/** 失败展示要的几样,从后端那份读出来:一句话(没有就是调用方给的那句兜底)、原文、原因和修法、复制的那段(整句原因)。 */
export function failureFields(source: FailureSource, fallback: string) {
  const summary = (source.error_summary ?? source.error ?? "").trim() || fallback;
  return {
    summary,
    detail: source.error_detail ?? null,
    fix: source.error_hint ?? null,
    copyText: (source.error ?? "").trim() || summary,
  };
}

/** 那一句最长多少字(和后端 failure_summary.SUMMARY_DETAIL_CHARS 一样):再长就是原文了,原文在「详情」里。 */
const SUMMARY_CHARS = 160;

/**
 * 只有原文的失败(工具调用交回的那段话、前端自己接到的报错 —— 没经过后端的失败归类):第一行当那一句(长了截到一句的长度),
 * 原文比它多出东西时进「详情」,复制的是整段原文。
 */
export function rawFailureFields(text: string, fallback: string) {
  const raw = text.trim();
  const first = raw.split(/\r?\n/)[0]?.trim() ?? "";
  const summary = first.length > SUMMARY_CHARS ? `${first.slice(0, SUMMARY_CHARS - 1).trimEnd()}…` : first;
  return { summary: summary || fallback, detail: raw && raw !== summary ? raw : null, fix: null, copyText: raw || summary };
}

type DataAttributes = { [key: `data-${string}`]: string | undefined };

export type FailureCardProps = {
  /** failed:跑挂了(红色的图标和标题);stopped:有人停下的,不是失败(灰色的停止图标) */
  status?: "failed" | "stopped";
  /** 短标题:「生成失败」「运行失败」「发布失败」「已停止」…… */
  title: string;
  /** 卡头右边的元信息(调用方摆好);紧凑档不摆 */
  meta?: React.ReactNode;
  /** 出了什么事:一句话 */
  summary?: string;
  /** 原文:比那一句多出信息时才有 */
  detail?: string | null;
  fix?: FailureFix | null;
  /** 「复制错误」复制的那一段(整句失败原因,报问题时最有用);不给就不摆复制 */
  copyText?: string | null;
  /** 动作行左边该点的那几颗(调用方给) */
  actions?: React.ReactNode;
  /** full:一张卡;compact:格子里摞着的一小块;inline:一行(列表行、格子底边的一条)。后两档的其余收进「详情」浮层 */
  size?: "full" | "compact" | "inline";
  /** 紧凑档在格子里居中还是靠左 */
  align?: "start" | "center";
  /** 紧凑档 / 一行档那一句最多几行 */
  lines?: 1 | 2 | 3 | 4;
  /** 一句话下面再补的内容(「已停止」那张的说明) */
  children?: React.ReactNode;
  className?: string;
} & DataAttributes;

export function FailureCard(props: FailureCardProps) {
  if (props.size === "compact") return <CompactFailure {...props} />;
  if (props.size === "inline") return <InlineFailure {...props} />;
  return <FullFailure {...props} />;
}

function statusIcon(status: "failed" | "stopped", size: number) {
  return status === "stopped" ? (
    <CircleStop size={size} className="text-muted-foreground" />
  ) : (
    <CircleAlert size={size} className="text-destructive" />
  );
}

const titleTone = (status: "failed" | "stopped") => (status === "stopped" ? "text-muted-foreground" : "text-destructive");

function dataAttributes(props: FailureCardProps): DataAttributes {
  return Object.fromEntries(Object.entries(props).filter(([key]) => key.startsWith("data-"))) as DataAttributes;
}

function FullFailure(props: FailureCardProps) {
  const { status = "failed", title, meta, className, children, actions, detail, copyText } = props;
  const t = useI18n();
  const titleId = React.useId();
  //: 没有该点的、也没有原文可展开时,动作那一行就只剩一颗复制 —— 不为它单占一行,放进卡头最右边
  const copyInHead = !actions && !detail && Boolean(copyText?.trim());
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className={cn("@container/failure grid w-full min-w-0 gap-2.5 rounded-lg border border-border bg-secondary/40 px-3.5 py-3", className)}
      data-failure=""
      data-failure-status={status}
      {...dataAttributes(props)}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1" data-failure-head="">
        <span className="flex shrink-0 items-center gap-1.5">
          <span aria-hidden className="flex">{statusIcon(status, 13)}</span>
          <strong id={titleId} className={cn("text-ui-xs font-semibold", titleTone(status))}>{title}</strong>
        </span>
        {/* 宽的时候元信息靠右和标题同一行;卡窄于 440px 时整块换到标题下面、靠左(不然长的那几条一半靠左一半靠右) */}
        {meta ? (
          <div className="ml-auto min-w-0 @max-[439px]/failure:ml-0 @max-[439px]/failure:basis-full" data-failure-meta="">
            {meta}
          </div>
        ) : null}
        {copyInHead ? (
          <CopyIconButton text={copyText!.trim()} label={t("failureCopyError")} className={cn("-my-1", !meta && "ml-auto")} data-failure-copy="" />
        ) : null}
      </div>
      <FailureBody {...props} copyText={copyInHead ? null : copyText} />
      {children}
    </div>
  );
}

/**
 * 那一句、原因和怎么修、动作行、原文 —— 卡里和紧凑档的「详情」浮层里是同一份。`detailOpen`:浮层里是用户点开「详情」才看到的,
 * 原文直接展开。
 */
function FailureBody({
  status = "failed",
  summary,
  detail,
  fix,
  copyText,
  actions,
  detailOpen = false,
}: FailureCardProps & { detailOpen?: boolean }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(detailOpen);
  const detailId = React.useId();
  const said = summary?.trim() ?? "";
  const copyable = (copyText ?? "").trim();
  const steps = (fix?.steps ?? []).filter((step) => step.text.trim() || step.command?.trim());
  const cause = fix?.cause?.trim() ?? "";
  const hasActions = Boolean(actions) || Boolean(detail) || Boolean(copyable);
  return (
    <>
      {said ? (
        <p
          className={cn(
            "m-0 whitespace-pre-wrap leading-[1.5] text-foreground [overflow-wrap:anywhere]",
            status === "stopped" ? "text-ui-sm" : "text-ui-md font-medium",
          )}
          data-failure-summary=""
        >
          {said}
        </p>
      ) : null}
      {cause || steps.length ? (
        <dl
          className="m-0 grid min-w-0 gap-2.5 rounded-md border border-border bg-background/70 px-3 py-2.5 text-ui-sm leading-[1.55]"
          data-failure-fix=""
        >
          {cause ? (
            <FixRow label={t("failureCause")}>
              <span className="text-foreground [overflow-wrap:anywhere]" data-failure-cause="">{cause}</span>
            </FixRow>
          ) : null}
          {steps.length ? (
            <FixRow label={t("failureFix")}>
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
      {hasActions ? (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5" data-failure-actions="">
          {actions}
          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            {detail ? (
              <Button
                variant="inline"
                aria-expanded={open}
                aria-controls={detailId}
                onClick={() => setOpen((value) => !value)}
                data-failure-detail-toggle=""
              >
                {t("failureDetail")}
                <ChevronDown size={12} aria-hidden className={cn("transition-transform duration-160", open && "rotate-180")} />
              </Button>
            ) : null}
            {copyable ? <CopyIconButton text={copyable} label={t("failureCopyError")} data-failure-copy="" /> : null}
          </div>
        </div>
      ) : null}
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
    </>
  );
}

/** 紧凑档、一行档里点开的「详情」浮层要不要摆:那一句之外还有东西(原文、原因和怎么修、动作)才摆。 */
function hasMore({ detail, fix, actions }: FailureCardProps): boolean {
  return Boolean(detail) || Boolean(fix?.cause) || Boolean(fix?.steps?.length) || Boolean(actions);
}

/**
 * 「详情」:紧凑档、一行档的其余部分(原因、怎么修、动作、原文、复制)收在点开的浮层里 —— 浮层里放得下能点的东西(悬停说明
 * 放不了按钮),键盘也能打开,Esc 关。按钮带 `nodrag nopan`:在画板、工作流画布的格子里点它不拖动画布。
 */
function MoreDetails(props: FailureCardProps & { centered?: boolean }) {
  const { status = "failed", title, centered = false } = props;
  const t = useI18n();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="inline" className="nodrag nopan shrink-0" data-failure-more="">
          {t("failureDetail")}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align={centered ? "center" : "start"}
        className="@container/failure grid w-[min(440px,calc(100vw-1rem))] gap-2.5 p-3 text-left"
        data-failure-popover=""
      >
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="flex">{statusIcon(status, 13)}</span>
          <strong className={cn("text-ui-xs font-semibold", titleTone(status))}>{title}</strong>
        </span>
        <FailureBody {...props} detailOpen />
      </PopoverContent>
    </Popover>
  );
}

/** 紧凑档:放不下一张卡的格子(画板格子、画布上的节点)。一枚图标、短标题、截断的那一句,其余在「详情」里。 */
function CompactFailure(props: FailureCardProps) {
  const { status = "failed", title, summary, align = "start", lines = 3, className } = props;
  const titleId = React.useId();
  const centered = align === "center";
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className={cn("grid w-full min-w-0 max-w-full gap-1", centered ? "justify-items-center text-center" : "justify-items-start", className)}
      data-failure=""
      data-failure-status={status}
      data-failure-size="compact"
      {...dataAttributes(props)}
    >
      <span className="flex min-w-0 items-center gap-1">
        <span aria-hidden className="flex">{statusIcon(status, 12)}</span>
        <strong id={titleId} className={cn("text-ui-2xs font-semibold", titleTone(status))}>{title}</strong>
      </span>
      {summary?.trim() ? (
        <Truncate lines={lines} className="max-w-full text-ui-2xs leading-relaxed text-foreground [overflow-wrap:anywhere]" data-failure-summary="">
          {summary}
        </Truncate>
      ) : null}
      {hasMore(props) ? <MoreDetails {...props} centered={centered} /> : null}
    </div>
  );
}

/**
 * 一行档:列表里的一行、格子底边的一条。图标、短标题 · 那一句(截断)、「详情」。和紧凑档同一份浮层。
 * 外面那一层(行的底色、圆角、定位)归调用方:这里只排这一行字。
 */
function InlineFailure(props: FailureCardProps) {
  const { status = "failed", title, summary, lines = 1, className } = props;
  const titleId = React.useId();
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className={cn("flex w-full min-w-0 items-start gap-1.5 text-ui-2xs leading-relaxed", className)}
      data-failure=""
      data-failure-status={status}
      data-failure-size="inline"
      {...dataAttributes(props)}
    >
      <span aria-hidden className="mt-[3px] flex shrink-0">{statusIcon(status, 11)}</span>
      <strong id={titleId} className={cn("shrink-0 font-semibold", titleTone(status))}>{title}</strong>
      {summary?.trim() ? (
        <Truncate lines={lines} className="min-w-0 flex-1 text-foreground [overflow-wrap:anywhere]" data-failure-summary="">
          {summary}
        </Truncate>
      ) : (
        <span className="flex-1" />
      )}
      {hasMore(props) ? <MoreDetails {...props} /> : null}
    </div>
  );
}

/** 「原因」「怎么修」一行:宽的时候标签在左边一栏(两行的标签对齐),窄的时候摞在上面。 */
function FixRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-1 @min-[440px]/failure:grid-cols-[5rem_minmax(0,1fr)] @min-[440px]/failure:gap-3">
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
          <CopyIconButton text={command} label={t("failureCopyCommand")} />
        </div>
      ) : null}
    </div>
  );
}

function CopyIconButton({ text, label, className, ...rest }: { text: string; label: string; className?: string } & DataAttributes) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <IconButton label={copied ? t("copied") : label} size="icon-xs" className={cn("shrink-0 text-muted-foreground", className)} onClick={copy} {...rest}>
      {copied ? <Check size={13} /> : <Copy size={13} />}
    </IconButton>
  );
}
