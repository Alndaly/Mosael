import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain, Check, ChevronDown, ChevronRight, CircleAlert, FileWarning, Loader2, Wrench } from "lucide-react";

import { api, assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AgentMarkdown } from "@/components/agent/Markdown";
import { useImagePreview } from "@/components/app/image-preview";
import { decodeByteFallback } from "@/lib/byteFallback";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ToolResultCard, toolResultData } from "./toolResultShapes";

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
function summarize(args: unknown): string | null {
  if (args == null) return null;
  if (typeof args === "string") return args;
  if (typeof args === "number" || typeof args === "boolean") return String(args);
  if (Array.isArray(args)) {
    const first = args.find((item) => typeof item === "string");
    return typeof first === "string" ? first : null;
  }
  if (typeof args === "object") {
    for (const value of Object.values(args as Record<string, unknown>)) {
      if (typeof value === "string" && value.trim()) return value;
    }
  }
  return null;
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
  const argText = format(tool.args);
  // Structure first: the runtimes hand us the result pre-stringified, so without unwrapping
  // there is nothing to render but the string.
  const data = React.useMemo(() => toolResultData(tool.result), [tool.result]);
  const card = tool.status === "error" ? null : <ToolResultCard value={data} />;
  const resultText = format(data ?? tool.result);
  const hasBody = Boolean(argText || resultText);
  const elapsed =
    typeof tool.usage?.duration_seconds === "number" ? formatElapsedSeconds(tool.usage.duration_seconds) : null;
  // Media the tool touched (an analyzed image, a generated clip, synthesized audio…) — shown as
  // playable/viewable cards so the agent's media "returns" are visible in chat, not just text.
  const assetIds = React.useMemo(
    () => (tool.status === "error" ? [] : [...collectAssetIds(tool.args, collectAssetIds(data))]),
    [tool.args, data, tool.status],
  );

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-muted",
        tool.status === "error" && "border-[color-mix(in_srgb,var(--destructive)_40%,var(--border))]",
      )}
    >
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-[9px] py-1.5 text-left text-xs text-muted-foreground transition-colors duration-100 enabled:cursor-pointer enabled:hover:bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]"
        onClick={() => hasBody && setOpen((value) => !value)}
        aria-expanded={hasBody ? open : undefined}
        disabled={!hasBody}
      >
        <span
          className={cn(
            "inline-flex flex-none text-muted-foreground",
            tool.status === "done" && "text-success",
            tool.status === "error" && "text-destructive",
          )}
          aria-hidden
        >
          {tool.status === "running" ? (
            <Loader2 size={12} className="animate-openstudio-spin" />
          ) : tool.status === "error" ? (
            <CircleAlert size={12} />
          ) : (
            <Check size={12} />
          )}
        </span>
        <Wrench size={11} className="flex-none text-muted-foreground" aria-hidden />
        <span className="flex-none font-mono text-foreground">{tool.name}</span>
        {preview && !open && <span className="min-w-0 flex-1 truncate font-mono text-ui-xs text-muted-foreground">{preview}</span>}
        <span className={cn("ml-auto flex-none text-ui-xs text-muted-foreground", tool.status === "error" && "text-destructive")}>
          {tool.status === "running" ? t("toolRunning") : tool.status === "error" ? t("toolFailed") : t("toolDone")}
        </span>
        {elapsed && <span className="flex-none text-ui-xs text-muted-foreground">{t("usageDuration").replace("{t}", elapsed)}</span>}
        {hasBody && (
          <ChevronRight
            size={13}
            className={cn("flex-none text-muted-foreground transition-transform duration-[120ms]", open && "rotate-90")}
            aria-hidden
          />
        )}
      </button>
      {/* 富结果卡(如 list_assets 的素材列表)可能几十条 → 封顶高度、内部滚动,别把整张卡撑到几屏高。 */}
      {card && <div className="max-h-[360px] min-w-0 overflow-y-auto overflow-x-hidden border-t border-border px-2.5 py-2">{card}</div>}
      {open && hasBody && (
        <div className="flex flex-col gap-2 border-t border-border px-[9px] py-2">
          {argText && (
            <div className="flex flex-col gap-[3px]">
              <span className="text-ui-2xs uppercase tracking-[0.04em] text-muted-foreground">{t("toolInput")}</span>
              <pre className="m-0 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-panel px-2 py-1.5 font-mono text-ui-xs leading-[1.5] text-foreground [word-break:break-word]">{argText}</pre>
            </div>
          )}
          {resultText && (
            <div className="flex flex-col gap-[3px]">
              <span className="text-ui-2xs uppercase tracking-[0.04em] text-muted-foreground">{t("toolResult")}</span>
              <pre className="m-0 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-panel px-2 py-1.5 font-mono text-ui-xs leading-[1.5] text-foreground [word-break:break-word]">{resultText}</pre>
            </div>
          )}
        </div>
      )}
      {assetIds.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border px-[9px] py-2">
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
    <div className="grid gap-1 rounded-md border border-dashed border-border bg-panel-subtle px-2.5 py-1.5">
      <button
        type="button"
        className="flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-left text-ui-xs text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        {done ? <Brain size={11} className="shrink-0" /> : <Loader2 size={11} className="shrink-0 animate-spin" />}
        <span className="min-w-0 flex-1 truncate">{done ? t("agentThought") : t("agentThinking")}</span>
        <ChevronDown size={11} className={cn("shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && text && (
        <p className="m-0 whitespace-pre-wrap text-ui-sm leading-[1.6] text-muted-foreground">{text}</p>
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
      {agentTurnParts(timeline).map((item, index) =>
        item.type === "tool" && item.tool ? (
          <ToolCalls key={`tool-${item.tool.id}-${index}`} tools={[item.tool]} />
        ) : item.type === "subtool" && item.tool ? (
          // 子智能体的一步:缩进 + 左边线,读作"这是上面那张 run_subagent 卡的内部动作"。
          <div key={`subtool-${item.tool.id}-${index}`} className="border-l-2 border-border/70 pl-2.5 ml-2">
            <ToolCalls tools={[item.tool]} />
          </div>
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
