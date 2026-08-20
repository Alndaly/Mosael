import { Bot } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";

import { CompactionNotice, type CompactionInfo } from "@/components/agent/ContextMeter";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { MessageUsageFooter, type AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { UserMessageContent } from "@/features/ai-studio/userMessage";

export type AgentMessage = components["schemas"]["AgentMessageOut"];

/**
 * 对话里的一条消息 —— 主智能体和子智能体共用的渲染语言。
 *
 * 子智能体本质上就是一个新的聊天智能体,它的会话视图必须和主对话长得一模一样:
 * 用户消息是右侧的窄气泡、助手消息带工具卡与悬停脚注、错误走同一张错误卡。
 * 所以这个组件从 ChatWorkspace 抽出来单独成文件 —— SubagentPanel 被 ChatWorkspace
 * 导入,反向去拿会成环,共用的东西就该住在两边都够得着的地方。
 */
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
  return (
    <div
      className={
        message.role === "assistant"
          ? "group/bubble relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]"
          : "ml-auto mr-[max(calc((100%-780px)/2),0px)] w-fit max-w-[min(560px,82%)] shrink-0 whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]"
      }
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
        <>
          {/* 来自另一个智能体会话的消息:右上挂一枚来源徽章 —— 用户扫一眼就知道
              这条不是自己发的。发起会话 id 放 title,悬停可查。 */}
          {payload?.from_agent_session && (
            <span
              className="mb-1 flex items-center gap-1 text-ui-2xs text-muted-foreground"
              title={payload.from_agent_session}
            >
              <Bot size={11} /> {t("chatFromAgentSession")}
            </span>
          )}
          <UserMessageContent content={message.content} />
        </>
      )}
      {/* 脚注只给助手回答:用户消息没有复制/耗时,免得药丸下方留一条空的悬停占位。 */}
      {message.role === "assistant" && (
        <MessageUsageFooter
          content={message.content}
          usageEvents={usageEvents}
          durationOverride={payload?.usage?.duration_seconds}
          className="opacity-0 transition-opacity duration-[120ms] group-hover/bubble:opacity-100"
        />
      )}
    </div>
  );
}
