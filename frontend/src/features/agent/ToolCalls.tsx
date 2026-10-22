import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Brain, Check, ChevronRight, CircleAlert, Loader2, Settings2, Sparkles, X } from "lucide-react";

import { getJob, type Confirmation, type JobSummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { JobDetailDialog } from "@/components/jobs/JobDetailDialog";
import { JobKindIcon, useJobKinds } from "@/components/jobs/jobKinds";
import { runStatusText } from "@/components/jobs/runStatus";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { HighlightedCode } from "@/features/agent/HighlightedCode";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Truncate } from "@/components/ui/truncate";
import { AGENT_ROW_BODY_CLASS, AGENT_ROW_CLASS, AGENT_ROW_ICON_CLASS, AGENT_ROW_TEXT_CLASS, AGENT_TEXT_BLOCK_CLASS, AGENT_TURN_BLOCKS_CLASS } from "@/features/agent/agentRow";
import { decodeByteFallback } from "@/features/agent/byteFallback";
import { NOISE_KEYS } from "@/features/agent/machineFields";
import { gotoSettings } from "@/lib/deepLink";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
import { ToolResultCard, detectShape, toolResultData } from "./toolResultShapes";
import { CitationContext } from "@/components/markdown/CitationLink";
import { collectCitations } from "@/features/agent/citations";
import { AgentPageViewsContext } from "@/features/agent/pageViews";
import { PendingConfirmationCard } from "@/features/agent/InlineConfirmations";
import { DecisionsContext, useToolCallConfirmation } from "@/features/agent/decisionsContext";
import { MediaPreviewGrid } from "@/features/agent/MediaPreview";
import { widgetOfTool, type AgentWidget } from "@/features/agent/turnOutputs";
import { AgentWidgetFrame } from "@/features/agent/AgentWidgetFrame";
import { EXPIRED, expiryLabel } from "@/features/agent/cardExpiry";

/** 工具调用卡的数据形态:后端从 sidecar 事件累积(host.py),流里实时更新、消息 payload 里持久化。 */
export type ToolCall = {
  id: string;
  name: string;
  args?: unknown;
  status: "running" | "done" | "error";
  result?: unknown;
  usage?: {
    started_at?: string;
    finished_at?: string;
    duration_seconds?: number;
  };
};

export type AgentTimelineItem =
  | { type: "text"; text: string }
  | { type: "tool"; tool: ToolCall }
  /** 子智能体内部的一步工具调用。父时间线只是实时运输载体；展示时按 parent_id 归入子会话。 */
  | { type: "subtool"; parent_id?: string; tool: ToolCall }
  /** 思考块。`done=false` 表示正在思考(展开并转圈),结束后默认收起。 */
  | { type: "thinking"; text: string; done?: boolean; duration_seconds?: number };

/** 取一段短摘要塞进折叠态标题(参考 Claude/Codex:折叠时也能看出这步在干嘛)。 */

/**
 * 摘要**按字段名挑**,不按出现顺序。
 *
 * 排在前面的是「一眼看出这一步在干什么」的那些:提示词、地址、要找的东西。挑不到就退回
 * 第一个不是噪音的字符串 —— 那至少比 workspace_id 强。
 */
const SUMMARY_KEYS = [
  "prompt",
  "text",
  "query",
  "keyword",
  "url",
  "path",
  "name",
  "title",
  "message",
  "content",
  "tool_name",
  "model",
];

function summarize(args: unknown): string | null {
  if (args == null) return null;
  if (typeof args === "string") return args;
  if (typeof args === "number" || typeof args === "boolean") return String(args);
  if (Array.isArray(args)) {
    const first = args.find((item) => typeof item === "string");
    return typeof first === "string" ? first : null;
  }
  if (typeof args !== "object") return null;
  const record = args as Record<string, unknown>;
  for (const key of SUMMARY_KEYS) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  for (const [key, value] of Object.entries(record)) {
    if (NOISE_KEYS.has(key)) continue;
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/** 展开的明细里也把噪音字段拿掉 —— 它们占的行数常常比真正的参数还多。 */
function withoutNoise(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const kept = Object.entries(value as Record<string, unknown>).filter(([key]) => !NOISE_KEYS.has(key));
  return kept.length > 0 ? Object.fromEntries(kept) : value;
}

/**
 * Asset ids mentioned anywhere in args/result, for the media preview cards.
 *
 * Only `asset_id`-shaped keys count. A bare `id` is deliberately NOT collected: a list of
 * assets already renders as a card with its own inline players, and treating every `id` as an
 * asset would also drag in workflow, project and confirmation ids, each costing a failed
 * request and a "missing media" tile.
 */
//: 工作流图是一份**计划**,不是这次调用碰过的媒体。图里节点配置上的 asset_id 指的是这条流程
//: 将来要读或要产出的东西 —— 官方模板留的占位、还没跑出来的产物,查过去多半 404,于是
//: `get_workflow` 的结果下面挂出两张「素材不可用」,而用户根本没让谁给他看素材。
//:
//: 判据用结构而不是工具名单:名单要跟着工具表走,而"图里的 id 是计划"这件事不会变。
const PLAN_KEYS = new Set(["graph"]);

export function collectAssetIds(value: unknown, out: Set<string> = new Set()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectAssetIds(item, out);
  } else if (value && typeof value === "object") {
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      if (PLAN_KEYS.has(key)) continue;
      //: 单数是一个 id,复数是一串 id。**两种都要认** —— 生成任务的产物正是放在
      //: `result.asset_ids` 里(domain/generation/runner),而此前只收字符串值,
      //: 于是数组里那几份刚生成出来的图,恰恰是这块预览最该显示的东西,一张都不显示。
      if (/asset_?id/i.test(key)) {
        if (typeof val === "string" && val.trim()) out.add(val.trim());
        else if (Array.isArray(val)) for (const item of val) if (typeof item === "string" && item.trim()) out.add(item.trim());
        else collectAssetIds(val, out);
      } else collectAssetIds(val, out);
    }
  }
  return out;
}

/** 把 args/result 渲染成可读文本:字符串原样,其余美化成 JSON。 */
function format(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * 这次调用开的确认卡走到了哪一步 —— 决定之后它就是工具行里的这一句,不再是一张卡。
 *
 * 「谁放的行」要说清:自动放行(本会话始终允许、自动 / 跳过档)和用户亲手点的不是一回事,
 * 写成同一个「已批准」等于替他认了一个他没做过的决定(同一条理由见 AutoApprovalTrace)。
 */
function decisionWord(card: Confirmation, t: ReturnType<typeof useI18n>): string {
  const who = card.decision_mode === "manual" ? t("confirmDecisionManual") : t("confirmDecisionAuto");
  switch (card.status) {
    case "pending":
      return t("confirmWaiting");
    case "approved":
      return `${who} · ${t("confirmOutcomeRunning")}`;
    case "executed":
      return `${who} · ${t("confirmOutcomeExecuted")}`;
    case "failed":
      return `${who} · ${t("confirmOutcomeFailed")}`;
    case "rejected":
      return t("confirmStatusRejected");
    default:
      //: 作废(这一轮已经结束,见 cardExpiry):按由头说。
      return t(expiryLabel(card.error));
  }
}

function ToolCallCard({ tool }: { tool: ToolCall }) {
  const t = useI18n();
  //: 这次调用开的确认卡(没有就是 null)。等决定时卡就摆在这一行下面;有了结论只剩行里那一句状态。
  const decision = useToolCallConfirmation(tool.id);
  //: 用户拒了 / 卡作废了:工具那边是「失败」(sidecar 抛的是「用户拒绝了该操作」),但这不是出了错 ——
  //: 是他做的决定。不标红、不自动摊开那句错误。
  const declined = decision?.status === "rejected" || decision?.status === EXPIRED;
  const failed = tool.status === "error" && !declined;
  //: 默认折叠:失败的原因不在明细里,在这一行下面那张失败展示里(不跟着折叠)。
  const [open, setOpen] = React.useState(false);
  const preview = summarize(tool.args);
  // 明细里也去噪:workspace_id 那几个占的行常常比真正的参数还多,而它们对读的人没有任何意义。
  const cleanArgs = React.useMemo(() => withoutNoise(tool.args), [tool.args]);
  const argText = format(cleanArgs);
  // 去噪之后只剩一个字段、而它的值就是摘要里那句 —— 再摆一遍 JSON 是纯重复。
  const argsAreJustPreview =
    preview != null &&
    cleanArgs != null &&
    typeof cleanArgs === "object" &&
    !Array.isArray(cleanArgs) &&
    Object.keys(cleanArgs as Record<string, unknown>).length === 1 &&
    Object.values(cleanArgs as Record<string, unknown>)[0] === preview;
  // Structure first: the runtimes hand us the result pre-stringified, so without unwrapping
  // there is nothing to render but the string.
  const data = React.useMemo(() => toolResultData(tool.result), [tool.result]);
  //: 这一页认得这次的结果(工作台「助手」的诊断、新标签页):画这一页给的,但仍属于这次工具调用的明细。
  const pageViews = React.useContext(AgentPageViewsContext);
  const pageCard = tool.status === "error" || !pageViews ? null : pageViews.toolResult(tool.name, data);
  const hasPageCard = pageCard !== null;
  const card = tool.status === "error" ? null : <ToolResultCard value={data} />;
  // 富卡认得出这份数据的形状时,**下面那块裸 JSON 就是同一份东西再摆一遍**。
  // 判据用 detectShape 而不是 card:card 是 JSX 元素,恒为真。
  const richShape = tool.status !== "error" && detectShape(data) !== null;
  const resultText = richShape || failed ? null : format(data ?? tool.result);
  // 富卡也算"有内容" —— 少了它这一项,一个「参数就是摘要 + 结果是富卡」的调用会算成没内容,
  // 整行不可展开,而那张富卡就永远看不到了。原注释警告过的正是这个陷阱(card 恒为真不能当判据),
  // 现在有了 richShape 这个真正的布尔值。
  const elapsed =
    typeof tool.usage?.duration_seconds === "number" ? formatElapsedSeconds(tool.usage.duration_seconds) : null;
  // Media the tool touched (an analyzed image, a generated clip, synthesized audio…) — shown as
  // playable/viewable cards so the agent's media "returns" are visible in chat, not just text.
  const assetIds = React.useMemo(
    () => (tool.status === "error" ? [] : [...collectAssetIds(tool.args, collectAssetIds(data))]),
    [tool.args, data, tool.status],
  );

  // **成功时不写「已完成」** —— 那个 ✓ 已经说过一遍了,再写一次只是在占地方。
  // 运行中和失败时保留:那两个词带的信息,图标传达不了全部(尤其失败,它要把视线拉过去)。
  // 开了确认卡的调用改说卡走到了哪一步:「已批准 · 已执行」比一个 ✓ 多说了一件事 —— 这一步是问过人的。
  const statusWord = decision ? null : tool.status === "running" ? t("toolRunning") : null;
  //: 跑挂了的那一步:状态词不写在行里 —— 下面那张失败展示的标题就是它(「失败」「手动 · 执行失败」),写两遍只是重复
  const decisionFailed = decision?.status === "failed";
  const statusText = decision && !decisionFailed ? <span data-decision={decision.status}>{decisionWord(decision, t)}</span> : statusWord;
  //: 出了什么事:批准后执行失败的看确认卡(后端摘好的那一句和原文),工具自己挂了看它交回的那段话
  const failure = decisionFailed && decision.error
    ? { summary: decision.error_summary || decision.error, detail: decision.error_detail ?? null, fix: decision.error_hint ?? null,
        copyText: decision.error }
    : failed
      ? rawFailureFields(format(data ?? tool.result) ?? "", t("toolFailed"))
      : null;
  const hasBody = Boolean(
    (argText && !argsAreJustPreview) || resultText || richShape || hasPageCard || failure || assetIds.length > 0,
  );
  // 页面专用结果和失败原因原先作为工具行的兄弟卡一直摊开,看起来像第二条消息。
  // 现在它们进这次调用的明细,结果刚到或失败时自动展开,仍然不会把重要回包藏起来。
  //: 做出来的素材不自动摊开这一行(也不进答案区,见 resultDocument):碰过的素材点开明细照样看得到;
  //: `show_widget` 的小界面同理,在明细里,不抢正文的位置。
  const revealResult = hasPageCard || Boolean(failure);
  React.useEffect(() => {
    if (revealResult) setOpen(true);
  }, [revealResult]);

  return (
    // 一次工具调用是对话里的**一条行内标记**,不是一张与正文并列的卡片 —— 所以用 Marker:
    // 折叠态就是安静的一行(没有填充、没有整圈边框),不再和旁边的正文抢分量;展开的明细挂在
    // 一条左竖线下面,读起来是"这一步的细节",而不是又一个内容块。
    <div className="w-full min-w-0" data-tool-call={tool.id}>
      <Marker
        asChild
        className={cn(
          AGENT_ROW_CLASS,
          "transition-colors duration-100",
          hasBody && "enabled:cursor-pointer enabled:hover:bg-muted",
        )}
      >
        <button
          type="button"
          onClick={() => hasBody && setOpen((value) => !value)}
          aria-expanded={hasBody ? open : undefined}
          disabled={!hasBody}
        >
          <MarkerIcon
            className={cn(
              "inline-flex items-center justify-center",
              tool.status === "done" && "text-success",
              failed && "text-destructive",
            )}
          >
            {tool.status === "running" ? (
              <Loader2 className={cn(AGENT_ROW_ICON_CLASS, "animate-mosael-spin")} />
            ) : declined ? (
              <X className={AGENT_ROW_ICON_CLASS} />
            ) : tool.status === "error" ? (
              <CircleAlert className={AGENT_ROW_ICON_CLASS} />
            ) : (
              <Check className={AGENT_ROW_ICON_CLASS} />
            )}
          </MarkerIcon>
          <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
            <span className="flex-none font-mono text-foreground">{tool.name}</span>
            {preview && !open && <Truncate className="flex-1 font-mono">{preview}</Truncate>}
            {/* 摘要占中间那一段(它可缩),状态与耗时**永远靠右** —— 但靠的是摘要那一栏的右缘,
                不是整行的最右。没有摘要时补一个占位,否则这一行的耗时会贴在名字后面,
                和上下几行对不齐。
                字号挂在 span 上:根是 button,那条全局 `button{font:inherit}` 会吃掉根上的字号。 */}
            {!(preview && !open) && <span className="min-w-0 flex-1" aria-hidden />}
            <span className="flex-none pl-1.5 text-ui-xs">
              {statusText}
              {statusText && elapsed && " · "}
              {elapsed && <span className="tabular-nums">{elapsed}</span>}
            </span>
          </MarkerContent>
          {/* 右侧只留展开箭头。状态词和耗时此前排在这儿,和左边的名字之间隔着一整片空白 ——
              一行里两组字各自贴边,中间那段空是最先被看见的东西,而它什么都不是。 */}
          {hasBody && (
            <ChevronRight
              className={cn("size-3 flex-none transition-transform duration-100", open && "rotate-90")}
              aria-hidden
            />
          )}
        </button>
      </Marker>
      {/* 等人拍板的卡就摆在发起它的这一行下面 —— 不是统一堆在对话末尾。 */}
      {decision?.status === "pending" ? (
        <div className="mt-1.5 min-w-0">
          <PendingConfirmationCard item={decision} />
        </div>
      ) : null}
      {/* 明细挂在左竖线下。富结果卡**跟着折叠走** —— 它此前在 open 之外,于是折叠只收得起
          原始 JSON,而真正占版面的那几十行结果一直摊着:头上明明有个收拢箭头,点了却不动。
          结果可能几十条 → 封顶高度、内部滚动,别把一步撑到几屏高。 */}
      {open && hasBody && (
        <div
          className={cn(AGENT_ROW_BODY_CLASS, "mt-1 flex min-w-0 flex-col gap-2")}
          data-tool-details=""
        >
          {failure ? (
            <FailureCard title={decisionFailed ? decisionWord(decision, t) : t("toolFailed")} {...failure} data-tool-failure={tool.id} />
          ) : null}
          {hasPageCard ? pageCard : card && <div className="max-h-[360px] min-w-0 overflow-y-auto overflow-x-hidden">{card}</div>}
          {argText && !argsAreJustPreview && (
            <div className="flex flex-col gap-[3px]">
              <span className="text-ui-2xs uppercase tracking-[0.04em] text-muted-foreground">{t("toolInput")}</span>
              <HighlightedCode
                code={argText}
                className="max-h-[220px] rounded-md border border-border bg-panel px-2 py-1.5 text-ui-xs text-foreground"
              />
            </div>
          )}
          {resultText && (
            <div className="flex flex-col gap-[3px]">
              <span className="text-ui-2xs uppercase tracking-[0.04em] text-muted-foreground">{t("toolResult")}</span>
              <HighlightedCode
                code={resultText}
                className="max-h-[220px] rounded-md border border-border bg-panel px-2 py-1.5 text-ui-xs text-foreground"
              />
            </div>
          )}
          {assetIds.length > 0 && (
            //: `reveal`:每张卡带一颗「在素材库中打开」—— 做出来的图现在只在过程里,这个出口要跟着过来。
            <MediaPreviewGrid assetIds={assetIds} reveal className={cn(AGENT_ROW_BODY_CLASS, "mt-1.5")} />
          )}
        </div>
      )}
    </div>
  );
}

/** 一轮里的工具调用序列,竖排成「任务步骤」(带左侧连接轨)。 */
export function ToolCalls({ tools }: { tools: ToolCall[] | undefined }) {
  if (!tools || tools.length === 0) return null;
  return (
    // 字号挂在容器上:行的根是 <button>,而全局那条 `button { font: inherit }` 会把根上的
    // 字号吃掉(同一段坑见 agentRow.ts 里 AGENT_ROW_TEXT_CLASS 的说明)。
    <div className={cn("flex w-full min-w-0 flex-col gap-1 self-stretch", AGENT_ROW_TEXT_CLASS)}>
      {tools.map((tool) =>
        // 读技能那一步不是一行原始 JSON:说「用了技能:X」,点开是它的做法(ADR 0040 §4)。失败的照普通工具行画,原因看得见。
        tool.name === "use_skill" && tool.status !== "error" ? (
          <SkillUseRow key={tool.id} tool={tool} />
        ) : (
          <ToolCallCard key={tool.id} tool={tool} />
        ),
      )}
    </div>
  );
}

/** `use_skill` 的回包里界面要的那几样(见后端 domain/agent/skills/runtime.use_skill)。 */
type SkillUse = { name?: string; title?: string; source?: string; instructions?: string; files?: { path: string }[] };

/**
 * 「用了技能:做带货短视频」。折叠时就这一句,点开看智能体读到的那份做法 —— 来源、正文、带的文件。
 *
 * 和工具行同一套形状(Marker):它也是「这一步做了什么」,只是这一步值得用人话说出来 —— 一个 `use_skill`
 * 加一串 JSON 对用户没有意义,「它照着哪份做法在做」才有。
 */
function SkillUseRow({ tool }: { tool: ToolCall }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const data = React.useMemo(() => toolResultData(tool.result), [tool.result]) as SkillUse | null;
  const requested = (tool.args as { name?: string } | undefined)?.name ?? "";
  const title = data?.title || data?.name || requested;
  const running = tool.status === "running";
  const body = data?.instructions ?? "";
  return (
    <div className="w-full min-w-0" data-tool-call={tool.id} data-skill-use={data?.name ?? requested}>
      <Marker
        asChild
        className={cn(AGENT_ROW_CLASS, "transition-colors duration-100", body && "enabled:cursor-pointer enabled:hover:bg-muted")}
      >
        <button type="button" onClick={() => body && setOpen((value) => !value)} aria-expanded={body ? open : undefined} disabled={!body}>
          <MarkerIcon className="inline-flex items-center justify-center text-primary">
            {running ? <Loader2 className={cn(AGENT_ROW_ICON_CLASS, "animate-mosael-spin")} /> : <Sparkles className={AGENT_ROW_ICON_CLASS} />}
          </MarkerIcon>
          <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
            <Truncate className="min-w-0 flex-1 text-foreground">
              {(running ? t("skillUsing") : t("skillUsed")).replace("{name}", title)}
            </Truncate>
            {data?.source && <span className="flex-none pl-1.5 text-ui-xs">{data.source}</span>}
          </MarkerContent>
          {body && (
            <ChevronRight className={cn("size-3 flex-none transition-transform duration-100", open && "rotate-90")} aria-hidden />
          )}
        </button>
      </Marker>
      {open && body && (
        <div className={cn(AGENT_ROW_BODY_CLASS, "mt-1 grid min-w-0 gap-2")} data-slot="skill-body">
          <div className="max-h-[360px] min-w-0 overflow-y-auto overflow-x-hidden text-ui-sm">
            <AgentMarkdown>{body}</AgentMarkdown>
          </div>
          {(data?.files?.length ?? 0) > 0 && (
            <p className="m-0 text-ui-xs text-muted-foreground">
              {t("skillUsedFiles").replace("{files}", (data?.files ?? []).map((file) => file.path).join("、"))}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** 父会话里实际画出来的工具调用 id。子智能体的步骤只在子会话里画,不能把确认卡挂回父会话。 */
export function toolCallIds(timelines: Iterable<AgentTimelineItem[] | undefined>): Set<string> {
  const ids = new Set<string>();
  for (const timeline of timelines) {
    for (const item of timeline ?? []) {
      if (item.type === "tool" && item.tool?.id) ids.add(item.tool.id);
    }
  }
  return ids;
}

export function agentTurnParts(
  timeline: AgentTimelineItem[] | undefined,
): AgentTimelineItem[] {
  if (!timeline?.length) return [];
  const parts: AgentTimelineItem[] = [];
  for (const item of timeline) {
    if (item.type === "text") {
      parts.push({ type: "text", text: item.text });
    } else if (item.type === "thinking") {
      parts.push({ type: "thinking", text: item.text, done: item.done, duration_seconds: item.duration_seconds });
    } else if (item.type === "subtool") {
      parts.push({ type: "subtool", parent_id: item.parent_id, tool: item.tool });
    } else {
      parts.push({ type: "tool", tool: item.tool });
    }
  }
  return parts;
}


/**
 * 后台任务回执的**结构化事实**(后端 receipts.receipt_payload)。收进步骤里只需要这几格;
 * 界面按当前语言重排,不读给模型读的那句 `content`。
 */
export type FoldedReceipt = { id: string; payload?: unknown };

type TurnBlock =
  | { type: "tools"; tools: ToolCall[] }
  | { type: "thinking"; text: string; done?: boolean; duration_seconds?: number }
  | { type: "text"; text: string }
  /** 被智能体接住的后台任务回执:它不在对话里单独占一条,而是这一轮的第一步(见 receiptWasCaught)。 */
  | { type: "receipts"; receipts: readonly FoldedReceipt[] };

/**
 * 把一轮的时间线切成**渲染块**,并且把**连着的工具调用并成一块**。
 *
 * 之前每个工具各自成块,于是三步连着调用时,它们之间用的是外层那个「块与块」的 gap-2.5
 * —— 和"一段正文之后跟一张卡"同一个间距。结果是三个本该读成一串步骤的东西,被摊成三条
 * 互不相干的行:ToolCalls 里那句"竖排成任务步骤"的设计从来没生效过,它内部的 gap-1 也
 * 一直是死代码(每次只传一个工具进去)。
 *
 * subtool 属于子智能体自己的会话。它仍保存在父时间线中作为流式传输与诊断载体,但不能在
 * 父对话里画成任务卡；子会话由 SubagentPanel 按 parent_id 接走。
 */
export function turnBlocks(timeline: AgentTimelineItem[] | undefined): TurnBlock[] {
  const blocks: TurnBlock[] = [];
  for (const item of agentTurnParts(timeline)) {
    if (item.type === "tool" && item.tool) {
      const last = blocks[blocks.length - 1];
      if (last?.type === "tools") last.tools.push(item.tool);
      else blocks.push({ type: "tools", tools: [item.tool] });
    } else if (item.type === "thinking") {
      blocks.push({ type: "thinking", text: item.text, done: item.done, duration_seconds: item.duration_seconds });
    } else if (item.type === "text" && item.text) {
      blocks.push({ type: "text", text: item.text });
    }
  }
  return blocks;
}

/**
 * 思考块。
 *
 * **进行中展开、结束后收起** —— Claude / Codex 都是这个形态:思考在发生时是有用的进度感,
 * 结束后它就是噪音,把答案挤到屏幕外。折叠标题保留下来是因为"它想过"本身是信息,
 * 而且用户随时可以翻回去看。
 *
 * 思考不进正文:它不是回答,复制按钮不该把它一起复制走,落库也不该混进消息内容。
 */
function ThinkingBlock({ text, done, durationSeconds }: { text: string; done?: boolean; durationSeconds?: number }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(!done);
  // 从"思考中"变成"已结束"时自动收起;用户手动展开过的不再强行改动。
  const wasDone = React.useRef(done);
  React.useEffect(() => {
    if (!wasDone.current && done) setOpen(false);
    wasDone.current = done;
  }, [done]);

  return (
    // **和工具调用同一套形状**(Marker):折叠态就是安静的一行,展开的正文挂在一条左竖线下。
    //
    // 此前它是一个虚线框 + 背景 + 内边距的块 —— 而折叠着的「已思考」什么都没说,却比旁边
    // 真正有内容的工具行重得多。同一段对话里两种同级的东西用两套形状,读的人会以为它们
    // 是两类不同的事,而它们都只是"这一步做了什么"。
    <div className="w-full min-w-0">
      <Marker
        asChild
        className={cn(AGENT_ROW_CLASS, "transition-colors duration-100 enabled:cursor-pointer enabled:hover:bg-muted")}
      >
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} disabled={!text}>
          <MarkerIcon className="inline-flex items-center justify-center">
            {done ? <Brain className={AGENT_ROW_ICON_CLASS} /> : <Loader2 className={cn(AGENT_ROW_ICON_CLASS, "animate-mosael-spin")} />}
          </MarkerIcon>
          <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
            <span className="flex-none">{done ? t("agentThought") : t("agentThinking")}</span>
            {/* 用时和工具卡同一个位置、同一种写法:靠右、等宽数字。后端在这段思考收起时记下
                (domain/agent/stream._close_open_thinking);还在想的时候没有,不显示。 */}
            <span className="min-w-0 flex-1" aria-hidden />
            {done && typeof durationSeconds === "number" && (
              <span className="flex-none pl-1.5 text-ui-xs tabular-nums">{formatElapsedSeconds(durationSeconds)}</span>
            )}
          </MarkerContent>
          {text && (
            <ChevronRight
              className={cn("size-3 flex-none transition-transform duration-100", open && "rotate-90")}
              aria-hidden
            />
          )}
        </button>
      </Marker>
      {open && text && (
        <div className={cn(AGENT_ROW_BODY_CLASS, "mt-1")}>
          <p className="m-0 whitespace-pre-wrap text-ui-sm leading-[1.6] text-muted-foreground">{text}</p>
        </div>
      )}
    </div>
  );
}

/**
 * 一轮回答里「过程」和「结果」的分界:**末尾连着的正文是结果,前面的全是过程**。
 *
 * 过程是智能体怎么做到的 —— 思考、工具调用、中途说的「我先查一下素材」;结果是它最后交给你的那段话。
 * 判据只看形状:最后一个非正文块之后的正文。中途那几句话夹在工具中间,读起来是旁白,不是答案;
 * 还在跑的时候也照这个切 —— 正在流出来的那段正文先当结果画,接着又调了工具,它就落回过程里。
 */
export function splitTurn(blocks: TurnBlock[]): { process: TurnBlock[]; result: TurnBlock[] } {
  let cut = blocks.length;
  while (cut > 0 && blocks[cut - 1].type === "text") cut -= 1;
  return { process: blocks.slice(0, cut), result: blocks.slice(cut) };
}

export type ResultDocItem =
  | { kind: "text"; text: string }
  | { kind: "widget"; widget: AgentWidget };

/**
 * **答案文档 = 智能体最后那段正文 + 它主动要展示的小界面**(维护者 2026-10-22)。
 *
 * 「答案区显示什么」是**智能体自己的决定**,不是渲染器的固定规则:
 *
 * - 要放图:在正文里写 `![说明](mosael-asset:<asset_id>)`,渲染前换成本地可取的地址;
 * - 要放一小块交互界面:调 `show_widget` —— 那个工具的契约就是「把这个拿给用户看」,所以它画在
 *   **答案里**(按时间线顺序和正文交织),不是埋进折叠的「已处理 · N 步」里;
 * - 工具**碰过 / 跑出来**的素材(生成任务的产物、回执带来的图)不自动摆进答案:要不要给人看,
 *   由它在正文里写引用决定。把「工具一产出就挂到答案下面」当固定规则是错的。
 */
export function resultDocument(blocks: TurnBlock[]): ResultDocItem[] {
  const { result } = splitTurn(blocks);
  const doc: ResultDocItem[] = [];
  for (const block of blocks) {
    if (block.type === "text") {
      if (result.includes(block) && block.text) doc.push({ kind: "text", text: block.text });
    } else if (block.type === "tools") {
      for (const tool of block.tools) {
        const widget = widgetOfTool(tool);
        if (widget) doc.push({ kind: "widget", widget });
      }
    }
  }
  return doc;
}

/** 过程有几步:每次工具调用、每段思考、每条被接住的回执各算一步。中途的旁白不算 —— 它不是一步动作。 */
function processSteps(process: TurnBlock[]): number {
  return process.reduce(
    (sum, block) =>
      sum +
      (block.type === "tools"
        ? block.tools.length
        : block.type === "thinking"
          ? 1
          : block.type === "receipts"
            ? block.receipts.length
            : 0),
    0,
  );
}

/**
 * 被智能体接住的后台任务回执 —— 折叠在「已处理 · N 步」里的一行,点开是任务详情。
 *
 * 为什么在这里:回执是那一轮的**由头**(后端把回执交给智能体,它随后说的那句话就是结论),
 * 所以它属于那一轮的步骤,而不是对话里另一条消息。**失败卡不在这一档**:带「查看任务 / 前往结果 /
 * 重新取回」的那张卡只留给**没被接住**的回执(见 ChatBubble.receiptWasCaught)。
 *
 * 行上不读 `content`(那是给模型读的、落库时冻结语言的一句),而是拿 payload 里的事实按当前语言重排。
 */
function ReceiptSteps({ receipts }: { receipts: readonly FoldedReceipt[] }) {
  return (
    <div className="grid gap-1" data-turn-receipts="">
      {receipts.map((receipt) => (
        <ReceiptStep key={receipt.id} receipt={receipt} />
      ))}
    </div>
  );
}

function ReceiptStep({ receipt }: { receipt: FoldedReceipt }) {
  const t = useI18n();
  const { kindOf } = useJobKinds();
  const payload = (receipt.payload ?? {}) as {
    job_id?: unknown;
    kind?: unknown;
    status?: unknown;
    subject?: unknown;
  };
  const kind = kindOf(typeof payload.kind === "string" ? payload.kind : "");
  const status = typeof payload.status === "string" ? payload.status : "";
  const subject = typeof payload.subject === "string" ? payload.subject.trim() : "";
  const jobId = typeof payload.job_id === "string" ? payload.job_id : "";
  const [detailJob, setDetailJob] = React.useState<JobSummary | null>(null);
  //: 详情现取(回执只带 job id);取不到由全局 mutation 兜底说一声,不是点了一下什么都没发生。
  const openTask = useMutation({
    mutationFn: () => getJob(jobId),
    onSuccess: (job) => setDetailJob(job),
  });

  return (
    <div className="w-full min-w-0">
      {/* 一行安静的步骤(ghost 档),点开是任务详情。不用原生 <button>:那是按钮,就该是 Button
          (档位、转圈、焦点圈、悬停说明都由它给 —— 见 design/nativeButtons.test.ts)。 */}
      <Button
        variant="ghost"
        size="xs"
        className="w-full min-w-0 justify-start gap-1.5 font-normal"
        loading={openTask.isPending}
        disabled={!jobId}
        onClick={() => jobId && openTask.mutate()}
        data-receipt-step={jobId}
      >
        <JobKindIcon meta={kind} size={12} />
        {/* 整句左组吃满剩余、内部截断:「后台任务 · 工作流 · 新工作流……」。主题是短语的
            末尾从句,不独立成栏 —— 单独占一栏读起来就是个来路不明的中间元素(维护者截图)。
            状态不吃 flex,永远钉在右缘。 */}
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          <span className="flex-none">{t("chatJobsTitle")}</span>
          {kind.label ? (
            <>
              <span className="flex-none text-muted-foreground" aria-hidden>·</span>
              <span className="flex-none">{kind.label}</span>
            </>
          ) : null}
          {subject ? (
            <>
              <span className="flex-none text-muted-foreground" aria-hidden>·</span>
              <Truncate className="text-muted-foreground">{subject}</Truncate>
            </>
          ) : null}
        </span>
        {status ? (
          <span className="flex-none text-ui-xs text-muted-foreground">{runStatusText(t, status)}</span>
        ) : null}
      </Button>
      <JobDetailDialog job={detailJob} onClose={() => setDetailJob(null)} />
    </div>
  );
}

function TurnBlockView({ block, index }: { block: TurnBlock; index: number }) {
  if (block.type === "tools") {
    // 连成一串的工具步骤共用**一个** ToolCalls,于是它们之间是块内的 gap-1,
    // 而不是外层这个"块与块之间"的 gap —— 见 turnBlocks 的说明。
    return <ToolCalls key={`tools-${block.tools[0].id}-${index}`} tools={block.tools} />;
  }
  if (block.type === "receipts") {
    return <ReceiptSteps key={`receipts-${index}`} receipts={block.receipts} />;
  }
  if (block.type === "thinking") {
    return <ThinkingBlock text={block.text} done={block.done} durationSeconds={block.duration_seconds} />;
  }
  // 补上和标记行同一份上下内缩(见 AGENT_TEXT_BLOCK_CLASS):不然"一个空行"会有三种宽度。
  return block.text ? (
    <div className={AGENT_TEXT_BLOCK_CLASS}>
      <AgentMarkdown>{decodeByteFallback(block.text)}</AgentMarkdown>
    </div>
  ) : null;
}

const NO_RECEIPTS: readonly FoldedReceipt[] = [];

/**
 * 一轮回答:**过程在上、可以收起;结果在下、一直摊着**(和 ChatGPT / Codex 同一个形态)。
 *
 * 此前过程和结果是同一串块:一次调了十来个工具的回答,答案被挤在一屏工具行下面,要往下翻才找得到;
 * 生成的图挂在 `get_job` 那一行的明细里,和「查了一下任务」混在一起。
 *
 * - **过程**收成一行摘要「已处理 · 6 步 · 32 秒」,点开是原样的那串步骤。还在跑的时候它摊着、实时在长
 *   (「处理中 · 3 步」),这一轮有了结果它自己收起;用户手动开合过的就照他的来。
 * - 三种时候**不收**:跑失败了(要看得见断在哪一步)、没有结果(这一轮就停在过程里,收起来什么都不剩)、
 *   有确认卡在等人拍板(卡就挂在发起它的那一行下面,见 ToolCallCard;PendingDecisions 也按「那一行看得见」
 *   决定要不要在对话末尾再摆一张)。
 * - **结果就是那段正文**(维护者 2026-10-22):答案区显示什么由智能体自己决定 —— 它把要展示的图写成
 *   `![说明](mosael-asset:<asset_id>)`、要的小界面写成内嵌 HTML,这些都是流式正文的一部分,边流边画。
 *   `show_widget` 的小界面是**智能体主动要展示**的东西,画在答案里(和正文按时间线交织);
 *   工具碰过 / 跑出来的素材留在过程里,要不要给人看由它在正文里写引用决定。
 *
 * 过程只有一段思考时不套摘要:「已处理 · 1 步」包着「已思考」是同一件事说两遍,思考块自己会收起。
 */
export function AgentTurnContent({
  timeline,
  running = false,
  failed = false,
  durationSeconds,
  foldedReceipts = NO_RECEIPTS,
}: {
  timeline?: AgentTimelineItem[];
  /** 这一轮还在跑(流式那一份)。 */
  running?: boolean;
  /** 这一轮以失败收场(消息带 error)。 */
  failed?: boolean;
  /** 这一轮的总用时(`payload.usage.duration_seconds`),写进过程摘要。 */
  durationSeconds?: number;
  /** 被智能体接住的后台任务回执(见 ChatBubble.receiptWasCaught)。它们收进过程摘要里,不单独占一条消息。
   *  调用方要给稳定的数组:气泡是 memo 的。 */
  foldedReceipts?: readonly FoldedReceipt[];
}) {
  const t = useI18n();
  const citations = React.useMemo(() => collectCitations(timeline), [timeline]);
  const ordered = React.useMemo(
    () =>
      foldedReceipts.length > 0
        ? [{ type: "receipts" as const, receipts: foldedReceipts } as TurnBlock, ...turnBlocks(timeline)]
        : turnBlocks(timeline),
    [timeline, foldedReceipts],
  );
  const { process } = React.useMemo(() => splitTurn(ordered), [ordered]);
  /** 答案文档:正文和「做出来的素材」按时间线顺序交织 —— 结果在产出它的位置,不在末尾另起一块(见 resultDocument)。 */
  const doc = React.useMemo(() => resultDocument(ordered), [ordered]);
  const decisions = React.useContext(DecisionsContext);
  const awaitingDecision = process.some(
    (block) => block.type === "tools" && block.tools.some((tool) => decisions?.byToolCall.get(tool.id)?.status === "pending"),
  );
  const hasResult = doc.length > 0;
  const settled = !running && !failed && hasResult;
  //: 用户亲手开合过就听他的(null = 没碰过,跟着状态走)。不用 effect 去"在跑完那一刻收起":
  //: 跟着状态算出来的开合,跑完自然就是收着的,而他点过的那一下也不会被下一次渲染抹掉。
  const [chosenOpen, setChosenOpen] = React.useState<boolean | null>(null);
  const processOpen = awaitingDecision || (chosenOpen ?? !settled);
  const steps = processSteps(process);
  const onlyThinking = process.length === 1 && process[0].type === "thinking";
  const summary = [
    (running ? t("agentProcessRunning") : t("agentProcessDone")).replace("{n}", String(steps)),
    !running && typeof durationSeconds === "number" ? formatElapsedSeconds(durationSeconds) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    // **间距由容器统一给**。此前每种块自带下外边距(思考 10px、工具卡 8px),而正文的
    // 末段被 `last-child:mb-0` 清零 —— 于是三种块之间的缝隙各不相同,正文后面紧跟一张卡时
    // 干脆贴在一起。grid + gap 一处说了算,也符合仓库里"纵向堆叠一律 grid/flex + gap"的约定。
    //
    // gap 之外还有一层:标记行自带 `py-1` 的热区,正文块没有,于是同一个 gap 在不同的邻居之间
    // 看着是三个值。正文块补上同一份内缩(AGENT_TEXT_BLOCK_CLASS),gap 相应收到 1.5 —— 加起来
    // 仍是原先最常见的那一档,只把"标记行挨着标记行"那 22px 收回来。
    // `grid-cols-[minmax(0,1fr)]` 不是装饰:单列 grid 的隐式列是 `auto`,也就是 **max-content**
    // —— 一个长 URL 或 32 位 session id 会把这一列撑到内容宽度,冲破外面那层 780px,而**同一个
    // grid 里的其它块(思考、正文)跟着一起变宽**,看起来像"整条消息比别的宽"。子项自己的
    // truncate 救不了:truncate 要父级先有确定宽度,而这里父级宽度正是由它的内容定的。
    <CitationContext.Provider value={citations}><div className={AGENT_TURN_BLOCKS_CLASS}>
      {process.length > 0 && (onlyThinking ? (
        <TurnBlockView block={process[0]} index={0} />
      ) : (
        <Disclosure
          label={summary}
          open={processOpen}
          onOpenChange={setChosenOpen}
          className="min-w-0"
          triggerClassName="px-1.5 py-1"
          //: 摊开的步骤挂在一条竖线下 —— 和工具行明细同一种"从这一行垂下来"的读法,
          //: 一眼分得清哪些是过程、从哪儿起是答案。
          contentClassName="ml-[13px] mt-1 border-l border-border pl-1.5"
        >
          <div className={AGENT_TURN_BLOCKS_CLASS} data-turn-process="">
            {process.map((block, index) => (
              <TurnBlockView key={`${block.type}-${index}`} block={block} index={index} />
            ))}
          </div>
        </Disclosure>
      ))}
      {hasResult && (
        <div className={AGENT_TURN_BLOCKS_CLASS} data-turn-result="">
          {doc.map((item, index) =>
            item.kind === "text" ? (
              <TurnBlockView key={`result-${index}`} block={{ type: "text", text: item.text }} index={index} />
            ) : (
              <AgentWidgetFrame key={`result-${index}`} widget={item.widget} />
            ),
          )}
        </div>
      )}
    </div></CitationContext.Provider>
  );
}

/** 失败轮的错误卡:标题 + 可展开的原始错误,而不是把「执行失败」当正常回答铺开。 */
/** 后端在失败的那一轮上记的机器原因(`payload.error_code`):这几种在气泡上给一个能点的去处。 */
const ERROR_FIXES: Record<string, { label: "agentConfigureModel" | "agentReauthorize"; go: () => void }> = {
  //: 没有可用的对话模型:去设置里配一个(和模型选择器空着时那颗按钮同一个去处)。
  no_chat_model: { label: "agentConfigureModel", go: () => gotoSettings("providers:chat") },
  //: 订阅连接的授权过期了(对方拒绝刷新):去模型供应商那一页,那条连接上就是「授权过期 · 重新授权」。
  oauth_expired: { label: "agentReauthorize", go: () => gotoSettings("providers:chat") },
};

/**
 * 一轮没跑完:和别处同一份失败展示 —— 标题「智能体执行失败」,那一句是这一轮记下的说法(后端写好的人话),原文(上游的原话)收进
 * 「详情」;认得出的原因给一颗能点的去处(没有对话模型 → 去配一个)。
 */
export function AgentErrorCard({ content, error, code }: { content: string; error?: string | null; code?: string | null }) {
  const t = useI18n();
  const fix = code ? ERROR_FIXES[code] : undefined;
  const summary = content.trim() || t("agentFailedTitle");
  return (
    <FailureCard
      title={t("agentFailedTitle")}
      summary={summary}
      detail={error && error.trim() !== summary ? error : null}
      copyText={error || summary}
      actions={fix ? (
        <Button variant="outline" size="xs" className="gap-1" onClick={fix.go}>
          <Settings2 size={13} />
          {t(fix.label)}
        </Button>
      ) : undefined}
      data-agent-turn-failed=""
    />
  );
}
