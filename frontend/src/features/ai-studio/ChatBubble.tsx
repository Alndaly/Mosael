import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";

import { CompactionNotice, type CompactionInfo } from "@/components/agent/ContextMeter";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { MessageFooter, MessageTime, MessageUsageFooter, type AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { UserMessageContent } from "@/features/ai-studio/userMessage";
import { cn } from "@/lib/utils";

export type AgentMessage = components["schemas"]["AgentMessageOut"];

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
 * 正好是那次对话在左侧列表里的名字 —— 看到就知道是哪一个。id 留在 title 属性里备查。
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
    <span className="flex items-center gap-1.5 text-ui-2xs text-muted-foreground" title={sessionId}>
      <Bot size={12} className="flex-none" />
      <span className="font-medium">{t("chatFromAgentSession")}</span>
      {title && (
        <>
          <span aria-hidden>·</span>
          <span className="min-w-0 truncate">{title}</span>
        </>
      )}
    </span>
  );
}

export function ChatBubble({ message, usageEvents }: { message: AgentMessage; usageEvents: AgentUsageEvent[] }) {
  const t = useI18n();
  const payload = message.payload as
    | {
        usage?: { duration_seconds?: number };
        timeline?: AgentTimelineItem[];
        compaction?: CompactionInfo;
        /** notify_agent_session 发来的:发起会话的 id(结构化来源,不靠信封文案)。 */
        from_agent_session?: string;
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
  // 另一个智能体会话发来的通知**不套用户气泡**。右侧气泡在这套界面里的意思是"坐在这儿的人
  // 说的",而这条不是 —— 它来自另一次对话。摆成左侧一块安静的内嵌,配一条来源抬头:形状本身
  // 就把"谁说的"讲清楚了,不必靠正文里一行方括号标签(那行现在只进提示词,见后端
  // host.agent_notice_envelope)。
  const fromAgent = message.role === "user" ? payload?.from_agent_session : undefined;
  // 外层只负责**摆位置**和挂 group,可见的那块(药丸/内嵌卡)在里面 —— 脚注要落在药丸
  // **下方**而不是它的内边距里,所以这两层必须分开。
  return (
    <div
      className={cn(
        "group/bubble",
        message.role === "assistant"
          ? "relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]"
          : fromAgent
            ? "mx-auto w-full max-w-[780px] shrink-0"
            : "ml-auto mr-[max(calc((100%-780px)/2),0px)] flex w-fit max-w-[min(560px,82%)] shrink-0 flex-col items-stretch",
      )}
    >
      {/* 自动压缩发生在这一轮开始前,标记就排在这条回复之前 —— 位置本身在说"从这里往前被整理过"。 */}
      {message.role === "assistant" && payload?.compaction && (
        <div className="mb-1.5">
          <CompactionNotice info={payload.compaction} />
        </div>
      )}
      {message.role === "assistant" ? (
        message.error ? (
          <AgentErrorCard content={message.content} error={message.error} />
        ) : (
          <AgentTurnContent timeline={payload?.timeline} />
        )
      ) : (
        <div
          className={
            fromAgent
              ? "grid gap-1.5 rounded-lg border border-border border-l-[3px] border-l-muted-foreground/40 bg-panel-subtle px-3 py-2.5 text-ui-md leading-[1.65] [word-break:break-word]"
              : "whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]"
          }
        >
          {fromAgent && <AgentOrigin sessionId={fromAgent} />}
          <div className={fromAgent ? "whitespace-pre-wrap" : undefined}>
            <UserMessageContent content={message.content} />
          </div>
        </div>
      )}
      {/* 两侧都有脚注,长得一样(见 MessageFooter):助手那边是耗时/tokens/计费,
          用户这边是发出的时间。都只在悬停时显形 —— 常态下这一行是空的,不该占视线。 */}
      {message.role === "assistant" ? (
        <MessageUsageFooter
          content={message.content}
          usageEvents={usageEvents}
          durationOverride={payload?.usage?.duration_seconds}
          className="opacity-0 transition-opacity duration-[120ms] group-hover/bubble:opacity-100"
        />
      ) : (
        <MessageFooter
          content={message.content}
          className="justify-end opacity-0 transition-opacity duration-[120ms] group-hover/bubble:opacity-100"
        >
          <MessageTime iso={message.created_at} />
        </MessageFooter>
      )}
    </div>
  );
}
