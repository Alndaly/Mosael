/**
 * **一段智能体对话在运行时的样子和能做的事**,AI 工作台的对话页和各工作区的助手面板共用这一份。
 *
 * 此前两边各写一遍:会话详情 / 消息 / 排队 / 用量四个查询,撤回 / 继续发送 / 插话 / 停止 / 整理上下文五个动作,
 * 发送之后的那一串(建会话 → 发 → 记下开跑 → 刷新清单 → 接上流)。维护热点 §20 说消息流和队列「只能在共享壳里维护」,
 * 而 AI 工作台是第二个壳 —— 两边已经各改过一次对方没改的地方。
 *
 * 这里不管**界面**(气泡、输入框、排队条怎么画,两边长得不一样),也不管**怎么拼消息体**(工作台把文本附件内联进正文,
 * 助手面板放进 context、还要带页面说明和引用的那一句):各自拼好交给 `send`。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JSONContent } from "@tiptap/react";
import { toast } from "sonner";

import {
  compactAgentSession,
  dropQueuedMessage,
  getAgentSession,
  listAgentMessages,
  listAgentQueue,
  listAgentUsageEvents,
  resumeQueuedMessage,
  sendAgentMessage,
  steerQueuedMessage,
  stopAgentSession,
} from "@/api/client";
import type { AgentMessageQuote } from "@/api/domains/sessions";
import { agentKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { markAgentTurnStarted } from "@/features/agent/agentTurnStarts";
import type { CompactionInfo, ContextInfo } from "@/features/agent/ContextMeter";
import type { CurrentAgentSession } from "@/features/agent/currentAgentSession";
import type { AgentUsageEvent } from "@/features/agent/messageUsage";
import { placePayload } from "@/features/agent/places";
import type { AgentReference } from "@/features/agent/references";
import { collectSkills } from "@/features/agent/SkillChip";
import { sessionPolling, transcriptPolling, useTranscriptFollowsSession } from "@/features/agent/transcriptFollowsSession";
import { useAgentTurnStream } from "@/features/agent/useAgentTurnStream";
import { useTurnElapsedSeconds } from "@/features/agent/useTurnElapsedSeconds";

/** 一条要发出去的消息:正文、引用、编辑器文档(有它才认得出「/」点名的技能)、附加说明、引用的那一句。 */
export interface AgentOutgoingMessage {
  content: string;
  references: AgentReference[];
  document?: JSONContent | null;
  context?: string;
  quote?: AgentMessageQuote | null;
}

export function useAgentConversation(current: CurrentAgentSession, workspaceId: string) {
  const t = useI18n();
  const qc = useQueryClient();
  //: 空串 = 还没有会话(草稿);各查询都以它为 enabled 条件。
  const sessionId = current.session?.id ?? "";
  const enabled = Boolean(sessionId);

  /** 会话详情:运行状态、上下文水位(列表接口不带 —— 那要为每段各算一次,而界面只看当前这段)。 */
  const session = useQuery({
    queryKey: agentKeys.session(sessionId),
    enabled,
    queryFn: () => getAgentSession(sessionId),
    refetchInterval: (query) => sessionPolling(query.state.data?.status === "running"),
    refetchOnWindowFocus: true,
  });
  const running = session.data?.status === "running";
  const stream = useAgentTurnStream(sessionId || null, running);
  //: 消息只在跑着的时候轮询;空闲时跟着会话的状态 / updated_at 变化重取一次(见 transcriptFollowsSession)。
  const messages = useQuery({
    queryKey: agentKeys.messages(sessionId),
    enabled,
    queryFn: () => listAgentMessages(sessionId),
    refetchInterval: transcriptPolling(running),
    refetchOnWindowFocus: true,
  });
  useTranscriptFollowsSession(sessionId, session.data);
  //: 计费 / 用量:按 agent_message_id 归到各条回复(见 MessageUsageFooter)。
  const usageEvents = useQuery({
    queryKey: agentKeys.usage(sessionId),
    enabled,
    queryFn: () => listAgentUsageEvents<AgentUsageEvent>(sessionId),
    refetchInterval: running ? 1200 : false,
    refetchOnWindowFocus: true,
  });
  const usageByMessage = React.useMemo(() => {
    const byMessage = new Map<string, AgentUsageEvent[]>();
    for (const event of usageEvents.data ?? []) {
      if (!event.agent_message_id) continue;
      byMessage.set(event.agent_message_id, [...(byMessage.get(event.agent_message_id) ?? []), event]);
    }
    return byMessage;
  }, [usageEvents.data]);
  //: 排在当前回答后面的。从服务端读,不在本地数:刷新页面、一轮中途结束都还对。
  //: **空闲时也要读**:按了停止,排着的那几条被扣下(D63),等人点「继续发送」。
  const queue = useQuery({
    queryKey: agentKeys.queue(sessionId),
    enabled,
    queryFn: () => listAgentQueue(sessionId),
    refetchInterval: running ? 1500 : false,
  });
  const queuedIds = React.useMemo(() => new Set((queue.data ?? []).map((message) => message.id)), [queue.data]);
  /** 水位由会话详情**现算**给出:想知道「还能聊多久」的时刻恰恰在开口之前,那时没有新的一轮带回这个数。 */
  const context = (session.data?.context ?? null) as ContextInfo | null;
  const elapsedSeconds = useTurnElapsedSeconds(running, stream.turnStartedAt);

  const refreshQueue = () => {
    void qc.invalidateQueries({ queryKey: agentKeys.queue(sessionId) });
    void qc.invalidateQueries({ queryKey: agentKeys.messages(sessionId) });
  };
  const cancelQueued = useMutation({
    mutationFn: (messageId: string) => dropQueuedMessage(sessionId, messageId),
    onSuccess: refreshQueue,
  });
  //: 「继续发送」:按停止时扣下的那条放回队列,空闲就当场开跑。
  const resumeQueued = useMutation({
    mutationFn: (messageId: string) => resumeQueuedMessage(sessionId, messageId),
    onSuccess: () => {
      refreshQueue();
      void qc.invalidateQueries({ queryKey: agentKeys.session(sessionId) });
    },
  });
  const steerQueued = useMutation({
    mutationFn: (messageId: string) => steerQueuedMessage(sessionId, messageId),
    onSuccess: (result) => {
      //: 这一轮先结束了,消息留在队里自己跑 —— 不说的话,人以为已经插进了这一轮。
      if (!result.steered) toast.message(t("chatSteerTooLate"));
      refreshQueue();
    },
  });
  const stopTurn = useMutation({
    mutationFn: () => stopAgentSession(sessionId),
    //: 两种结果都不用说:停下了看得见这一轮结束;停一个刚结束的是看不见的竞态。
    meta: { silentError: true },
  });
  const compact = useMutation({
    mutationFn: () => compactAgentSession<{ compaction: CompactionInfo | null }>(sessionId),
    //: 压成功了对话里会多一条整理记录;**没得压和压失败必须说出来**,否则只是 loading 闪一下。
    onSuccess: (result) => {
      void messages.refetch();
      void qc.invalidateQueries({ queryKey: agentKeys.session(sessionId) });
      if (!result?.compaction) toast.message(t("agentCompactNothing"));
    },
    onError: (error) => toast.error(`${t("agentCompactFailed")}:${(error as Error).message}`),
  });

  //: 发送:草稿就先在这一处建一段。`running` 不拦 —— 一轮中途打的字是更正,后端把它插进这一轮(pi 的 steering 队列)。
  const { attach: attachStream } = stream;
  const send = useMutation({
    mutationFn: async ({ content, references, document, context: extra, quote }: AgentOutgoingMessage) => {
      const targetId = (await current.ensure()).id;
      //: 「/」点名的技能(ADR 0040 §4):全文由后端挂到这一轮。
      const skills = document ? collectSkills(document) : [];
      const message = await sendAgentMessage(targetId, {
        content,
        references,
        ...(extra ? { context: extra } : {}),
        ...(document ? { body_document: document } : {}),
        ...(quote ? { quote } : {}),
        ...(skills.length ? { skills } : {}),
        //: 这一句是在哪说的:决定这一轮发哪些工具(ADR 0044 §8)。
        place: placePayload(current.place),
      });
      return { message, targetId };
    },
    onSuccess: ({ targetId }) => {
      markAgentTurnStarted(qc, targetId);
      void qc.invalidateQueries({ queryKey: agentKeys.sessions(workspaceId) });
      void attachStream(targetId);
    },
  });

  return {
    sessionId,
    session,
    running,
    stream,
    elapsedSeconds,
    messages,
    usageEvents,
    usageByMessage,
    queue,
    queuedIds,
    context,
    cancelQueued,
    resumeQueued,
    steerQueued,
    stopTurn,
    compact,
    send,
  };
}

export type AgentConversation = ReturnType<typeof useAgentConversation>;
