import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";

import { CompactionNotice, type CompactionInfo } from "@/features/agent/ContextMeter";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem, type FoldedReceipt } from "@/features/agent/ToolCalls";
import { AnsweredChoiceCard, type AnsweredChoice } from "@/features/agent/AnsweredChoice";
import { MessageFooter, MessageTime, MessageUsageFooter, type AgentUsageEvent } from "@/features/agent/messageUsage";
import { CHAT_ASSISTANT_ROW_CLASS, CHAT_USER_PILL_CLASS, CHAT_USER_ROW_CLASS } from "@/features/agent/agentRow";
import type { JSONContent } from "@tiptap/react";

import { UserMessageContent } from "@/features/agent/userMessage";
import { JOB_RECEIPT_ROLE, JobReceiptNotice, isWaitingReceipt } from "@/features/agent/JobReceiptNotice";
import type { ImagePreviewItem } from "@/components/app/image-preview";
import type { AgentMessageQuote } from "@/api/domains/sessions";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

export type AgentMessage = components["schemas"]["AgentMessageOut"];

/** 判定只认这几格:完整消息、流里刚拼出来的都够用。 */
export type TranscriptMessage = { id: string; role: string; payload?: unknown; error?: string | null };

/** 后端给「这一轮被重启掐断」的稳定标记(`host.RESTART_ERROR_KIND`,落在 `payload.error_kind`)。
 *  **不拿文案判断** —— 文案会翻译、会改。和 ChatWorkspace.tallyTurnFailures 同一份事实;
 *  那个函数住在页面组件里,这里不能反向依赖它(会成环)。 */
const RESTART_ERROR_KIND = "restart";

function payloadOf(message: TranscriptMessage): Record<string, unknown> | null {
  const payload = message.payload;
  return typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : null;
}

/** 这一轮是被后端重启掐断的:它不是结论,不能算「接住了回执」。 */
function interruptedByRestart(message: TranscriptMessage): boolean {
  return payloadOf(message)?.error_kind === RESTART_ERROR_KIND;
}

/** 回执之后**第一条**正常助手消息的 id(跳过被重启掐断的轮次);还没有就是 null。 */
function nextAnswerId(messages: readonly TranscriptMessage[], index: number): string | null {
  for (let i = index + 1; i < messages.length; i += 1) {
    const next = messages[i];
    if (next.role !== "assistant") continue;
    if (interruptedByRestart(next)) continue;
    return next.id;
  }
  return null;
}

/**
 * 智能体**接住了**这条回执吗 —— 信息架构:回执不该在对话里当一条独立消息常驻,对话里留的是结论
 * (智能体那句话);只有**没接住**的回执才显式出现。
 *
 * 两样已有事实:
 * 1. 回执自己还没交给智能体(`payload.undelivered`,后端 `_hand_over_receipts` 交出去时会把这个键删掉);
 * 2. 它之后有一条助手消息,且那一轮不是被重启掐断的中断说明。
 *
 * 没有 `undelivered` 的老回执照同一条规则走:后面有正常回答就算接住,没有就算没接住 ——
 * 不为旧数据写特例分支。
 */
export function receiptWasCaught(messages: readonly TranscriptMessage[], index: number): boolean {
  const message = messages[index];
  if (!message || message.role !== JOB_RECEIPT_ROLE) return false;
  if (isWaitingReceipt(message)) return false;
  return nextAnswerId(messages, index) !== null;
}

/**
 * 把**被接住**的回执归给接住它的那一轮回答 —— 回执就是那一轮的由头(后端 drain 把它交给智能体,
 * 智能体随后说的那句话就是结论),也是 `turnOutputs.receivedAssetIdsByMessage` 已经把回执带来的
 * 素材归给的那条消息,两处位置一致。
 *
 * 没接住的回执**不在表里**:它们要在对话里显式出现(带「查看任务 / 前往结果」),不能被收起来。
 */
export function caughtReceiptsByMessage(
  messages: readonly TranscriptMessage[],
): Map<string, TranscriptMessage[]> {
  const byMessage = new Map<string, TranscriptMessage[]>();
  for (let i = 0; i < messages.length; i += 1) {
    const message = messages[i];
    if (message.role !== JOB_RECEIPT_ROLE || !receiptWasCaught(messages, i)) continue;
    const answerId = nextAnswerId(messages, i);
    if (answerId === null) continue;
    byMessage.set(answerId, [...(byMessage.get(answerId) ?? []), message]);
  }
  return byMessage;
}

/**
 * 对话里的一条消息 —— 主智能体和子智能体共用的渲染语言。
 *
 * 子智能体本质上就是一个新的聊天智能体,它的会话视图必须和主对话长得一模一样:
 * 用户消息是右侧的窄气泡、助手消息带工具卡与悬停脚注、错误走同一张错误卡。
 * 所以这个组件从 ChatWorkspace 抽出来单独成文件 —— SubagentPanel 被 ChatWorkspace
 * 导入,反向去拿会成环,共用的东西就该住在两边都够得着的地方。
 */
/**
 * 「这条是另一个智能体会话发来的」。
 *
 * 显示的是**对方会话的标题**,不是它的 id:一串 32 位十六进制对读的人没有任何意义,而标题
 * 正好是那次对话在左侧列表里的名字 —— 看到就知道是哪一个。id 放在悬停说明里备查。
 */
function AgentOrigin({ sessionId }: { sessionId: string }) {
  const t = useI18n();
  const source = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => api<{ title?: string }>(`/api/agent/sessions/${sessionId}`),
    staleTime: 60_000,
    retry: false,
  });
  const title = source.data?.title?.trim();
  return (
    <Hint label={title || sessionId} hint={title ? sessionId : undefined}>
      <span className="flex items-center gap-1.5 text-ui-2xs text-muted-foreground">
        <Bot size={12} className="flex-none" />
        <span className="font-medium">{t("chatFromAgentSession")}</span>
        {title && (
          <>
            <span aria-hidden>·</span>
            <Truncate>{title}</Truncate>
          </>
        )}
      </span>
    </Hint>
  );
}

/**
 * **memo 的。** 对话页每一秒都可能重渲(运行计时、会话轮询、开关右栏),一段三百条的对话每次都把三百个气泡
 * 连同里面的 Markdown、代码高亮、工具行再算一遍(前端架构分析 FA-04)。消息对象由 React Query 的结构共享保持
 * 同一个引用,调用方负责让 `usageEvents`、`mediaGallery` 也只在真变了的时候换(见 ChatWorkspace 的 NO_USAGE)。
 */
export const ChatBubble = React.memo(function ChatBubble({
  message,
  usageEvents,
  mediaGallery,
  workspaceId,
  receivedAssetIds,
  foldedReceipts,
}: {
  message: AgentMessage;
  usageEvents: AgentUsageEvent[];
  mediaGallery?: ImagePreviewItem[];
  /** 念这一条记在哪个工作区的账上,也决定要不要 ai 权限(见 routes/agent.speak)。 */
  workspaceId: string;
  /** 助手消息:回执带来、该画进这一轮结果里的素材(见 turnOutputs.receivedAssetIdsByMessage)。 */
  receivedAssetIds?: readonly string[];
  /** 助手消息:被这一轮**接住**的回执(见 receiptWasCaught),收进「已处理 · N 步」里。
   *  没被接住的不传进来 —— 它们作为独立的一条显式出现(见 JobReceiptNotice)。
   *  调用方要给稳定的数组:气泡是 memo 的。 */
  foldedReceipts?: readonly FoldedReceipt[];
}) {
  const payload = message.payload as
    | {
        usage?: { duration_seconds?: number };
        timeline?: AgentTimelineItem[];
        compaction?: CompactionInfo;
        /** 用户消息:编辑器原样的文档,气泡照它把引用画回胶囊。 */
        body_document?: JSONContent;
        /** notify_agent_session 发来的:发起会话的 id(结构化来源,不靠信封文案)。 */
        from_agent_session?: string;
        /** 用户消息:这条是一次**选择的回执**,问的什么、选的哪一项都在里面。 */
        answers?: AnsweredChoice;
        /** 用户消息:带着的笔记摘录(笔记页的选区),气泡里画成可点的一行。 */
        quote?: AgentMessageQuote;
      }
    | null;
  // 手动压缩留下的是一条 role=system、内容为空的消息,只承载压缩标记。
  if (message.role === "system") {
    return payload?.compaction ? (
      <div className="mx-auto w-full max-w-[780px] shrink-0">
        <CompactionNotice info={payload.compaction} />
      </div>
    ) : null;
  }
  // 后台任务的回执:一行任务通知,不是谁说的话(用户截图:摆成用户气泡,「这不是我发送的」)。
  // **被智能体接住的不该走到这里** —— 容器按 `receiptWasCaught` 跳过那条消息、把它交给接住它的
  // 那一轮的 `foldedReceipts`。走到这里的是没接住的:那一条要显式出现。
  if (message.role === JOB_RECEIPT_ROLE) {
    return (
      <div className="mx-auto w-full max-w-[780px] shrink-0">
        <JobReceiptNotice content={message.content} payload={message.payload} />
      </div>
    );
  }
  // 另一个智能体会话发来的通知**不套用户气泡**。右侧气泡在这套界面里的意思是"坐在这儿的人
  // 说的",而这条不是 —— 它来自另一次对话。摆成左侧一块安静的内嵌,配一条来源抬头:形状本身
  // 就把"谁说的"讲清楚了,不必靠正文里一行方括号标签(那行现在只进提示词,见后端
  // host.agent_notice_envelope)。
  const fromAgent = message.role === "user" ? payload?.from_agent_session : undefined;
  const inset = Boolean(fromAgent);
  // 外层只负责**摆位置**和挂 group,可见的那块(药丸/内嵌卡)在里面 —— 脚注要落在药丸
  // **下方**而不是它的内边距里,所以这两层必须分开。
  return (
    <div
      className={cn(
        "group/bubble",
        message.role === "assistant"
          ? CHAT_ASSISTANT_ROW_CLASS
          : inset
            ? "mx-auto w-full max-w-[780px] shrink-0"
            : CHAT_USER_ROW_CLASS,
      )}
    >
      {/* 自动压缩发生在这一轮开始前,标记就排在这条回复之前 —— 位置本身在说"从这里往前被整理过"。 */}
      {message.role === "assistant" && payload?.compaction && (
        <div className="mb-1.5">
          <CompactionNotice info={payload.compaction} />
        </div>
      )}
      {message.role === "assistant" ? (
        /* **失败的那一轮,已经做过的事照样要看得见。** 此前这里是二选一:只要带 error 就
           只画错误卡 —— 一次跑了三分钟、调了十来次工具的对话,最后一步断线,用户看到的就只剩
           一句「执行失败」。过程在上、失败原因在下,顺序本身就说明了"跑到哪儿断的"。 */
        <>
          <AgentTurnContent
            timeline={payload?.timeline}
            failed={Boolean(message.error)}
            durationSeconds={payload?.usage?.duration_seconds}
            receivedAssetIds={receivedAssetIds}
            foldedReceipts={foldedReceipts}
          />
          {message.error && (
            <div className={payload?.timeline?.length ? "mt-2" : undefined}>
              <AgentErrorCard content={message.content} error={message.error} code={(message.payload as { error_code?: string } | null)?.error_code} />
            </div>
          )}
        </>
      ) : (
        <div
          className={
            inset
              ? "grid gap-1.5 rounded-lg border border-border border-l-[3px] border-l-muted-foreground/40 bg-panel-subtle px-3 py-2.5 text-ui-md leading-[1.65] [word-break:break-word]"
              : CHAT_USER_PILL_CLASS
          }
        >
          {fromAgent && <AgentOrigin sessionId={fromAgent} />}
          <div className={inset ? "whitespace-pre-wrap" : undefined}>
            {/* 一次选择在对话里不该退化成一段自述:有结构就照结构画,没有(老消息)才退回正文。 */}
            {payload?.answers ? (
              <AnsweredChoiceCard answers={payload.answers} />
            ) : (
              <UserMessageContent content={message.content} document={payload?.body_document} mediaGallery={mediaGallery} quote={payload?.quote} />
            )}
          </div>
        </div>
      )}
      {/* 两侧都有脚注,长得一样(见 MessageFooter):助手那边是耗时/tokens/计费,
          用户这边是发出的时间。都只在悬停时显形 —— 常态下这一行是空的,不该占视线。 */}
      {message.role === "assistant" ? (
        <MessageUsageFooter
                  messageId={message.id}
          workspaceId={workspaceId}
          content={message.content}
          usageEvents={usageEvents}
          durationOverride={payload?.usage?.duration_seconds}
          className="opacity-0 transition-opacity duration-100 group-hover/bubble:opacity-100"
        />
      ) : (
        <MessageFooter
          content={message.content}
          className="justify-end opacity-0 transition-opacity duration-100 group-hover/bubble:opacity-100"
        >
          <MessageTime iso={message.created_at} />
        </MessageFooter>
      )}
    </div>
  );
});
