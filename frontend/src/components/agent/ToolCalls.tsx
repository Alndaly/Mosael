import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Check, ChevronRight, CircleAlert, FileWarning, Loader2 } from "lucide-react";

import { api, assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AgentMarkdown } from "@/components/agent/Markdown";
import { useImagePreview } from "@/components/app/image-preview";
import { HighlightedCode } from "@/components/agent/HighlightedCode";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { decodeByteFallback } from "@/lib/byteFallback";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ToolResultCard, detectShape, toolResultData } from "./toolResultShapes";

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
  /** 子智能体内部的一步工具调用,挂在发起它的 run_subagent 调用(parent_id)名下。
      嵌套显示在父卡之后 —— 没有它,run_subagent 是一段几十秒的静默。 */
  | { type: "subtool"; parent_id?: string; tool: ToolCall }
  /** 思考块。`done=false` 表示正在思考(展开并转圈),结束后默认收起。 */
  | { type: "thinking"; text: string; done?: boolean };

/** 取一段短摘要塞进折叠态标题(参考 Claude/Codex:折叠时也能看出这步在干嘛)。 */
/**
 * 只有机器需要的字段。它们在摘要里毫无意义,在展开的明细里也只是噪音。
 *
 * 折叠行此前显示的是 `browser_open fd8620bd80ec4c88a03d73b8b17b7f6b` —— 那是 workspace_id,
 * 因为老的取法是「对象里第一个字符串值」,而参数里第一个往往就是它。一串 32 位十六进制
 * 占满整行,而真正说明这一步在干什么的 url 被挤掉了。
 */
const NOISE_KEYS = new Set([
  "workspace_id",
  "project_id",
  "session_id",
  "confirmation_id",
  "requested_by",
  "instance_id",
]);

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
function collectAssetIds(value: unknown, out: Set<string> = new Set()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectAssetIds(item, out);
  } else if (value && typeof value === "object") {
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      if (/asset_?id/i.test(key) && typeof val === "string" && val.trim()) out.add(val.trim());
      else collectAssetIds(val, out);
    }
  }
  return out;
}

/** 媒体预览卡:按素材 kind 渲染图/视频/音频,让智能体「返回」的素材在聊天里可见可播。 */
function MediaPreview({ assetId }: { assetId: string }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const asset = useQuery({
    queryKey: ["agent-asset", assetId],
    queryFn: () => api<Asset>(`/api/assets/${assetId}`),
    staleTime: 60_000,
    retry: false,
  });
  if (asset.isLoading) {
    return (
      <div className="m-0 flex max-w-[240px] items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-2 text-ui-xs text-muted-foreground">
        <Loader2 size={13} className="animate-openstudio-spin" />
      </div>
    );
  }
  if (asset.isError || !asset.data) {
    return (
      <div className="m-0 flex max-w-[240px] items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-2 text-ui-xs text-muted-foreground">
        <FileWarning size={13} /> {t("agentMediaMissing")}
      </div>
    );
  }
  const src = assetFileUrl(asset.data.id);
  return (
    <figure className="m-0 flex max-w-[240px] flex-col gap-1">
      {asset.data.kind === "image" ? (
        <button
          type="button"
          className="block cursor-zoom-in border-0 bg-transparent p-0 focus-visible:rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          onClick={() => openImagePreview({ src, title: asset.data.name })}
        >
          <img className="max-h-[200px] w-full rounded-lg border border-border bg-black object-contain" src={src} alt={asset.data.name} loading="lazy" />
        </button>
      ) : asset.data.kind === "video" ? (
        <video className="max-h-[200px] w-full rounded-lg border border-border bg-black object-contain" src={src} controls preload="metadata" />
      ) : asset.data.kind === "audio" ? (
        <audio className="w-[240px]" src={src} controls preload="metadata" />
      ) : (
        <div className="m-0 flex max-w-[240px] items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-2 text-ui-xs text-muted-foreground">
          <FileWarning size={13} /> {asset.data.name}
        </div>
      )}
      <figcaption className="truncate text-ui-xs text-muted-foreground">{asset.data.name}</figcaption>
    </figure>
  );
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

function ToolCallCard({ tool }: { tool: ToolCall }) {
  const t = useI18n();
  // 失败默认展开(让人一眼看到出错原因),其余默认折叠。
  const [open, setOpen] = React.useState(tool.status === "error");
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
  const card = tool.status === "error" ? null : <ToolResultCard value={data} />;
  // 富卡认得出这份数据的形状时,**下面那块裸 JSON 就是同一份东西再摆一遍**。
  // 判据用 detectShape 而不是 card:card 是 JSX 元素,恒为真。
  const richShape = tool.status !== "error" && detectShape(data) !== null;
  const resultText = richShape ? null : format(data ?? tool.result);
  // 富卡也算"有内容" —— 少了它这一项,一个「参数就是摘要 + 结果是富卡」的调用会算成没内容,
  // 整行不可展开,而那张富卡就永远看不到了。原注释警告过的正是这个陷阱(card 恒为真不能当判据),
  // 现在有了 richShape 这个真正的布尔值。
  const hasBody = Boolean((argText && !argsAreJustPreview) || resultText || richShape);
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
  const statusWord =
    tool.status === "running" ? t("toolRunning") : tool.status === "error" ? t("toolFailed") : null;

  return (
    // 一次工具调用是对话里的**一条行内标记**,不是一张与正文并列的卡片 —— 所以用 Marker:
    // 折叠态就是安静的一行(没有填充、没有整圈边框),不再和旁边的正文抢分量;展开的明细挂在
    // 一条左竖线下面,读起来是"这一步的细节",而不是又一个内容块。
    <div className="w-full min-w-0">
      <Marker
        asChild
        className={cn(
          "rounded-md px-1.5 py-1 transition-colors duration-100",
          hasBody && "enabled:cursor-pointer enabled:hover:bg-muted",
          tool.status === "error" && "text-destructive",
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
              tool.status === "error" && "text-destructive",
            )}
          >
            {/* 图标显式带 size-3:Marker 会把没有 size- 类的 svg 统一撑到 16px,
                而这一行的节奏是按 12px 图标定的。 */}
            {tool.status === "running" ? (
              <Loader2 className="size-3 animate-openstudio-spin" />
            ) : tool.status === "error" ? (
              <CircleAlert className="size-3" />
            ) : (
              <Check className="size-3" />
            )}
          </MarkerIcon>
          <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
            <span className="flex-none font-mono text-foreground">{tool.name}</span>
            {preview && !open && <span className="min-w-0 flex-1 truncate font-mono">{preview}</span>}
            {/* 摘要占中间那一段(它可缩),状态与耗时**永远靠右** —— 但靠的是摘要那一栏的右缘,
                不是整行的最右。没有摘要时补一个占位,否则这一行的耗时会贴在名字后面,
                和上下几行对不齐。
                字号挂在 span 上:根是 button,那条全局 `button{font:inherit}` 会吃掉根上的字号。 */}
            {!(preview && !open) && <span className="min-w-0 flex-1" aria-hidden />}
            <span className="flex-none pl-1.5 text-ui-xs">
              {statusWord}
              {statusWord && elapsed && " · "}
              {elapsed && <span className="tabular-nums">{elapsed}</span>}
            </span>
          </MarkerContent>
          {/* 右侧只留展开箭头。状态词和耗时此前排在这儿,和左边的名字之间隔着一整片空白 ——
              一行里两组字各自贴边,中间那段空是最先被看见的东西,而它什么都不是。 */}
          {hasBody && (
            <ChevronRight
              className={cn("size-3 flex-none transition-transform duration-[120ms]", open && "rotate-90")}
              aria-hidden
            />
          )}
        </button>
      </Marker>
      {/* 明细挂在左竖线下。富结果卡**跟着折叠走** —— 它此前在 open 之外,于是折叠只收得起
          原始 JSON,而真正占版面的那几十行结果一直摊着:头上明明有个收拢箭头,点了却不动。
          结果可能几十条 → 封顶高度、内部滚动,别把一步撑到几屏高。 */}
      {open && hasBody && (
        <div
          className={cn(
            "ml-[13px] mt-1 flex min-w-0 flex-col gap-2 border-l border-border pl-3",
            tool.status === "error" && "border-[color-mix(in_srgb,var(--destructive)_40%,var(--border))]",
          )}
        >
          {card && <div className="max-h-[360px] min-w-0 overflow-y-auto overflow-x-hidden">{card}</div>}
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
        </div>
      )}
      {/* 媒体产出**不跟着折叠** —— 生成出来的那张图是这一步的成果,不是它的明细。 */}
      {assetIds.length > 0 && (
        <div className="ml-[13px] mt-1.5 flex flex-wrap gap-2 border-l border-border pl-3">
          {assetIds.map((id) => (
            <MediaPreview key={id} assetId={id} />
          ))}
        </div>
      )}
    </div>
  );
}

/** 一轮里的工具调用序列,竖排成「任务步骤」(带左侧连接轨)。 */
export function ToolCalls({ tools }: { tools: ToolCall[] | undefined }) {
  if (!tools || tools.length === 0) return null;
  return (
    <div className="flex w-full min-w-0 flex-col gap-1 self-stretch">
      {tools.map((tool) => (
        <ToolCallCard key={tool.id} tool={tool} />
      ))}
    </div>
  );
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
      parts.push({ type: "thinking", text: item.text, done: item.done });
    } else if (item.type === "subtool") {
      parts.push({ type: "subtool", parent_id: item.parent_id, tool: item.tool });
    } else {
      parts.push({ type: "tool", tool: item.tool });
    }
  }
  return parts;
}


type TurnBlock =
  | { type: "tools"; tools: ToolCall[] }
  | { type: "thinking"; text: string; done?: boolean }
  | { type: "text"; text: string };

/**
 * 把一轮的时间线切成**渲染块**,并且把**连着的工具调用并成一块**。
 *
 * 之前每个工具各自成块,于是三步连着调用时,它们之间用的是外层那个「块与块」的 gap-2.5
 * —— 和"一段正文之后跟一张卡"同一个间距。结果是三个本该读成一串步骤的东西,被摊成三条
 * 互不相干的行:ToolCalls 里那句"竖排成任务步骤"的设计从来没生效过,它内部的 gap-1 也
 * 一直是死代码(每次只传一个工具进去)。
 *
 * 子步(subtool)和普通工具一起并:它们在视觉上本来就是同一串步骤,分开只会在中间豁一个口。
 */
export function turnBlocks(timeline: AgentTimelineItem[] | undefined): TurnBlock[] {
  const blocks: TurnBlock[] = [];
  for (const item of agentTurnParts(timeline)) {
    if ((item.type === "tool" || item.type === "subtool") && item.tool) {
      const last = blocks[blocks.length - 1];
      if (last?.type === "tools") last.tools.push(item.tool);
      else blocks.push({ type: "tools", tools: [item.tool] });
    } else if (item.type === "thinking") {
      blocks.push({ type: "thinking", text: item.text, done: item.done });
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
function ThinkingBlock({ text, done }: { text: string; done?: boolean }) {
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
        className="rounded-md px-1.5 py-1 transition-colors duration-100 enabled:cursor-pointer enabled:hover:bg-muted"
      >
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} disabled={!text}>
          {/* 图标显式带 size-3:Marker 会把没有 size- 类的 svg 统一撑到 16px,
              而这一行的节奏是按 12px 图标定的(同 ToolCallCard)。 */}
          <MarkerIcon className="inline-flex items-center justify-center">
            {done ? <Brain className="size-3" /> : <Loader2 className="size-3 animate-openstudio-spin" />}
          </MarkerIcon>
          <MarkerContent className="flex min-w-0 flex-1 items-baseline gap-1.5">
            <span className="flex-none">{done ? t("agentThought") : t("agentThinking")}</span>
          </MarkerContent>
          {text && (
            <ChevronRight
              className={cn("size-3 flex-none transition-transform duration-[120ms]", open && "rotate-90")}
              aria-hidden
            />
          )}
        </button>
      </Marker>
      {open && text && (
        <div className="ml-[13px] mt-1 border-l border-border pl-3">
          <p className="m-0 whitespace-pre-wrap text-ui-sm leading-[1.6] text-muted-foreground">{text}</p>
        </div>
      )}
    </div>
  );
}

/** Assistant answer renderer: preserves text/tool event order when payload.timeline exists. */
export function AgentTurnContent({
  timeline,
}: {
  timeline?: AgentTimelineItem[];
}) {
  return (
    // **间距由容器统一给**。此前每种块自带下外边距(思考 10px、工具卡 8px),而正文的
    // 末段被 `last-child:mb-0` 清零 —— 于是三种块之间的缝隙各不相同,正文后面紧跟一张卡时
    // 干脆贴在一起。grid + gap 一处说了算,也符合仓库里"纵向堆叠一律 grid/flex + gap"的约定。
    // `grid-cols-[minmax(0,1fr)]` 不是装饰:单列 grid 的隐式列是 `auto`,也就是 **max-content**
    // —— 一个长 URL 或 32 位 session id 会把这一列撑到内容宽度,冲破外面那层 780px,而**同一个
    // grid 里的其它块(思考、正文)跟着一起变宽**,看起来像"整条消息比别的宽"。子项自己的
    // truncate 救不了:truncate 要父级先有确定宽度,而这里父级宽度正是由它的内容定的。
    <div className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
      {turnBlocks(timeline).map((item, index) =>
        item.type === "tools" ? (
          // 连成一串的工具步骤共用**一个** ToolCalls,于是它们之间是块内的 gap-1,
          // 而不是外层这个"块与块之间"的 gap-2.5 —— 见 turnBlocks 的说明。
          <ToolCalls key={`tools-${item.tools[0].id}-${index}`} tools={item.tools} />
        ) : item.type === "thinking" ? (
          <ThinkingBlock key={`thinking-${index}`} text={item.text} done={item.done} />
        ) : item.type === "text" && item.text ? (
          <AgentMarkdown key={`text-${index}`}>{decodeByteFallback(item.text)}</AgentMarkdown>
        ) : null,
      )}
    </div>
  );
}

/** 失败轮的错误卡:标题 + 可展开的原始错误,而不是把「执行失败」当正常回答铺开。 */
export function AgentErrorCard({ content, error }: { content: string; error?: string | null }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <div className="flex flex-col gap-[5px] rounded-lg border border-[color-mix(in_srgb,var(--destructive)_40%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_8%,var(--muted))] px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-ui-sm text-destructive">
        <CircleAlert size={14} />
        <span>{content || t("agentFailedTitle")}</span>
      </div>
      {error && (
        <>
          <button type="button" className="self-start text-ui-xs text-muted-foreground underline" onClick={() => setOpen((value) => !value)}>
            {t("chatErrorDetail")}
          </button>
          {open && <pre className="m-0 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-panel px-2 py-1.5 font-mono text-ui-xs leading-[1.5] text-foreground [word-break:break-word]">{error}</pre>}
        </>
      )}
    </div>
  );
}
