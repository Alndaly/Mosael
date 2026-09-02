import React from "react";
import { Bot, ChevronDown, ChevronRight, CircleAlert, Loader2, X } from "lucide-react";

import type { AgentTimelineItem, ToolCall } from "@/components/agent/ToolCalls";
import { ChatBubble, type AgentMessage as ChatMessage } from "@/features/ai-studio/ChatBubble";
import { chatMediaGallery } from "@/features/ai-studio/userMessage";
import { TraceView } from "@/features/ai-studio/trace/TraceView";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { InspectorCard } from "@/components/agent/InspectorCard";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 子智能体的查看入口与会话视图。
 *
 * 照 DSH(及其 AgentTeams 插件)的形态:子代理是**有自己会话的**,主界面通过面包屑切进去看,
 * 它有自己的 对话/轨迹 两个视图 —— 不是一个弹窗。我们的子代理跑在 sidecar 进程内、结束即散,
 * 所以"会话"由存档(run_subagent 结果里的 details.subagent)合成:任务=它收到的提问,
 * 轨迹=它的阶段性文字与每一步工具调用。看得到全貌,但不可继续 —— 这一点如实呈现
 * (DSH 的可继续建立在子代理是持久会话之上,我们的不是)。
 *
 * 三个入口指向同一个视图:头部「N 个子代理」下拉、右侧「智能体环境」的子代理区块、
 * (对话流里的 run_subagent 卡只是普通卡,不再内嵌子步 —— 过程在子会话里看)。
 */

type SubagentArchive = {
  task: string;
  steps: number;
  error: string | null;
  trace: ({ type: "text"; text: string } | { type: "tool"; id: string; name: string; args?: unknown; result?: unknown; isError?: boolean })[];
};

export type SubagentRun = {
  /** run_subagent 那次调用的 ToolCall(状态、耗时都在它身上)。 */
  call: ToolCall;
  archive: SubagentArchive | null;
  /** 还在跑:工具卡本身 running,或已派发(非阻塞)但存档还没回填。 */
  running: boolean;
};

/** 从时间线里挑出所有 run_subagent 调用,并尽力解出各自的存档。 */
export function collectSubagentRuns(timeline: AgentTimelineItem[] | undefined): SubagentRun[] {
  const runs: SubagentRun[] = [];
  for (const item of timeline ?? []) {
    if (item.type !== "tool" || item.tool?.name !== "run_subagent") continue;
    const archive = readArchive(item.tool.result);
    // 非阻塞派发:卡本身立刻 done(回执是「已派发」),子智能体还在后台跑,
    // 存档(details.subagent)要等它跑完才回填 —— 这段时间也是「进行中」。
    const dispatched = readDispatched(item.tool.result);
    runs.push({ call: item.tool, archive, running: item.tool.status === "running" || (dispatched && !archive) });
  }
  return runs;
}

function readDispatched(result: unknown): boolean {
  if (result == null) return false;
  let value: unknown = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return false;
    }
  }
  return Boolean((value as { details?: { subagent_dispatched?: boolean } }).details?.subagent_dispatched);
}

function readArchive(result: unknown): SubagentArchive | null {
  if (result == null) return null;
  let value: unknown = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  const details = (value as { details?: { subagent?: unknown } }).details;
  const archive = details?.subagent as SubagentArchive | undefined;
  if (!archive || !Array.isArray(archive.trace)) return null;
  return archive;
}

/** 子代理在列表里的名字:任务的第一行。id 对人没有意义,任务才是它的身份。 */
export function subagentRunLabel(run: SubagentRun): string {
  const task = run.archive?.task ?? (run.call.args as { task?: string } | undefined)?.task ?? "";
  return task.split("\n")[0].trim() || run.call.id;
}

function StatusDot({ run }: { run: SubagentRun }) {
  // 后台派发的卡瞬间就 done 了,点的颜色要跟**子智能体**的死活走,不是跟那张回执卡。
  const status = run.running
    ? "running"
    : run.archive?.error || run.call.status === "error"
      ? "error"
      : run.archive
        ? "done"
        : run.call.status;
  return (
    <span
      className={cn(
        "h-1.5 w-1.5 shrink-0 rounded-full bg-border",
        status === "running" && "bg-primary animate-pulse",
        status === "done" && "bg-success",
        status === "error" && "bg-destructive",
      )}
      aria-hidden
    />
  );
}

function RunMeta({ run }: { run: SubagentRun }) {
  const t = useI18n();
  return (
    <>
      {run.archive
        ? t("chatSubagentSteps").replace("{n}", String(run.archive.steps))
        : run.running
          ? t("chatSubagentRunning")
          : t("chatSubagentNoTrace")}
      {run.archive?.error ? ` · ${run.archive.error.slice(0, 60)}` : ""}
    </>
  );
}

/** 头部「N 个子代理」下拉。点一项进入它的会话视图(onOpen 由 ChatWorkspace 落实)。 */
export function SubagentButton({
  timeline,
  onOpen,
}: {
  timeline: AgentTimelineItem[] | undefined;
  onOpen: (run: SubagentRun) => void;
}) {
  const t = useI18n();
  const runs = React.useMemo(() => collectSubagentRuns(timeline), [timeline]);
  const [open, setOpen] = React.useState(false);
  if (runs.length === 0) return null;
  const running = runs.some((run) => run.running);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost" className="h-7 gap-1 text-ui-xs text-muted-foreground">
          {running ? <Loader2 size={12} className="animate-mosael-spin" /> : <Bot size={12} />}
          {t("chatSubagents").replace("{n}", String(runs.length))}
          <ChevronDown size={11} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] p-1">
        <div className="grid max-h-[300px] gap-px overflow-y-auto">
          {runs.map((run, index) => (
            <button
              key={`${run.call.id}-${index}`}
              type="button"
              // min-w-0:弹层是固定宽的,这个按钮是 grid 子项,长任务名会把整列撑出弹层
              // (真机看到文字顶穿右边)。名字最多两行,超出省略 —— 单行省略对"以一串
              // UUID 开头"的任务名太狠,两行正好露出人写的那半句。
              className="grid w-full min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-1.5 gap-y-0.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted"
              onClick={() => {
                setOpen(false);
                onOpen(run);
              }}
            >
              {/* 状态点和第一行文字对中:点自身 6px,首行行高约 17px,垫出差值的一半。 */}
              <span className="flex pt-[5px]">
                <StatusDot run={run} />
              </span>
              <span className="min-w-0 text-ui-xs leading-snug text-foreground line-clamp-2 [word-break:break-word]">
                {subagentRunLabel(run)}
              </span>
              {typeof run.call.usage?.duration_seconds === "number" ? (
                <span className="timecode pt-[2px] text-ui-2xs text-muted-foreground">
                  {formatElapsedSeconds(run.call.usage.duration_seconds)}
                </span>
              ) : (
                <span />
              )}
              <span className="col-start-2 text-ui-2xs text-muted-foreground">
                <RunMeta run={run} />
              </span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** 右侧「智能体环境」里的子代理区块。
 *
 * 和概览、最近工具**同一种卡**(InspectorCard):此前它是夹在两张卡之间的裸列表,三块三种
 * 视觉语言(真机截图一眼看出)。行内是 状态点 + 截断的任务名(悬停看全文)+ 步数 + 箭头 ——
 * 任务名常以一串 UUID 开头,不截断整块就被它撑破。 */
export function InspectorSubagentList({
  timeline,
  onOpen,
}: {
  timeline: AgentTimelineItem[] | undefined;
  onOpen: (run: SubagentRun) => void;
}) {
  const t = useI18n();
  const runs = React.useMemo(() => collectSubagentRuns(timeline), [timeline]);
  if (runs.length === 0) return null;
  return (
    <InspectorCard icon={Bot} title={t("chatSubagentsTitle")} aside={String(runs.length)}>
      <div className="grid gap-0.5">
        {runs.map((run, index) => {
          const label = subagentRunLabel(run);
          return (
            <button
              key={`${run.call.id}-${index}`}
              type="button"
              className="-mx-1 grid min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-1.5 rounded border-0 bg-transparent px-1 py-1 text-left text-ui-xs text-foreground transition-colors hover:bg-panel"
              onClick={() => onOpen(run)}
              title={label}
            >
              <StatusDot run={run} />
              <span className="min-w-0 truncate">{label}</span>
              {run.archive && (
                <span className="shrink-0 tabular-nums text-ui-2xs text-muted-foreground">
                  {t("chatSubagentSteps").replace("{n}", String(run.archive.steps))}
                </span>
              )}
              <ChevronRight size={11} className="shrink-0 text-muted-foreground" aria-hidden />
            </button>
          );
        })}
      </div>
    </InspectorCard>
  );
}

/** 面包屑:主会话名 / 子代理名 ✕。点主会话名或 ✕ 返回。 */
export function SubagentBreadcrumb({
  sessionTitle,
  run,
  onBack,
}: {
  sessionTitle: string;
  run: SubagentRun;
  onBack: () => void;
}) {
  const t = useI18n();
  const label = subagentRunLabel(run);
  return (
    // flex-1 + min-w-0:头部行是 flex,这个组件作为子项默认 min-width:auto —— 任务名是一整段
    // 带 UUID 的长文本,不给收缩许可它就把整行顶穿(真机上面包屑铺满一屏,正是"崩了"的样子)。
    <div className="flex min-w-0 flex-1 items-center gap-1.5 text-ui-xs">
      <button
        type="button"
        className="max-w-[180px] shrink-0 cursor-pointer truncate border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
        onClick={onBack}
        title={sessionTitle}
      >
        {sessionTitle}
      </button>
      <span className="shrink-0 text-muted-foreground/60" aria-hidden>/</span>
      <span className="flex min-w-0 flex-1 items-center gap-1.5 font-medium text-foreground">
        <Bot size={12} className="shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate" title={label}>{label}</span>
      </span>
      <Button size="icon" variant="ghost" className="ml-1 h-6 w-6 shrink-0" aria-label={t("close")} onClick={onBack}>
        <X size={12} />
      </Button>
    </div>
  );
}

/** 存档 → 合成消息:让子代理的会话能喂给主界面同一套渲染(对话用 timeline,轨迹用 TraceView)。 */
function synthesize(run: SubagentRun): { timeline: AgentTimelineItem[]; messages: unknown[] } {
  const archive = run.archive;
  if (!archive) return { timeline: [], messages: [] };
  const timeline: AgentTimelineItem[] = archive.trace.map((item) =>
    item.type === "text"
      ? { type: "text", text: item.text }
      : {
          type: "tool",
          tool: {
            id: item.id,
            name: item.name,
            args: item.args,
            result: item.result,
            status: item.isError ? "error" : "done",
          } as ToolCall,
        },
  );
  // 结论正文 = 轨迹里最后一段助手文字(脚注的复制按钮复制的就是它)。
  const lastText = [...archive.trace].reverse().find((item) => item.type === "text");
  const messages = [
    { id: `${run.call.id}:task`, role: "user", content: archive.task, payload: {}, created_at: null },
    {
      id: `${run.call.id}:run`,
      role: "assistant",
      content: lastText?.type === "text" ? lastText.text : "",
      error: archive.error,
      payload: { timeline, usage: { duration_seconds: run.call.usage?.duration_seconds } },
      created_at: null,
    },
  ];
  return { timeline, messages };
}

/** 子代理的会话视图:它自己的 对话 / 轨迹。占据主内容区,由面包屑返回。 */
export function SubagentSessionView({ run }: { run: SubagentRun }) {
  const t = useI18n();
  const [view, setView] = React.useState<"chat" | "trace">("chat");
  const { timeline, messages } = React.useMemo(() => synthesize(run), [run]);
  const mediaGallery = React.useMemo(() => chatMediaGallery(messages as ChatMessage[]), [messages]);

  if (!run.archive) {
    return (
      <div className="grid min-h-0 place-items-center p-6">
        <p className="m-0 flex items-center gap-1.5 text-ui-sm text-muted-foreground">
          <CircleAlert size={13} />
          {run.running ? t("chatSubagentRunning") : t("chatSubagentNoTrace")}
        </p>
      </div>
    );
  }
  return (
    // min-w-0 一路给下去:内容里有宽表格、长 id,少一层收缩许可就从右边溢出去(真机截图)。
    <div className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)]">
      <div className="flex min-w-0 items-center gap-2 border-b border-border px-3 py-1.5">
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border" role="tablist">
          {(["chat", "trace"] as const).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={view === item}
              onClick={() => setView(item)}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground",
                view === item && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {t(item === "chat" ? "chatTabConversation" : "chatTabTrace")}
            </button>
          ))}
        </div>
      </div>
      {view === "trace" ? (
        <TraceView messages={messages as never} streamTimeline={[]} usageEvents={[]} />
      ) : (
        /* 主对话同一套容器与同一个 ChatBubble:子智能体本质就是一个新的聊天智能体,
           它的对话就该长得和主对话一模一样 —— 任务是右侧的用户气泡,产出是带工具卡
           和悬停脚注的助手消息,失败走同一张错误卡(所以 tabs 行不再单独挂红字)。 */
        <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-4 pt-7">
          {(messages as ChatMessage[]).map((message) => (
            <ChatBubble key={message.id} message={message} usageEvents={[]} mediaGallery={mediaGallery} />
          ))}
        </div>
      )}
    </div>
  );
}
