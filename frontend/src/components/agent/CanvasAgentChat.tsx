import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  CornerDownRight,
  Loader2,
  Move,
  PanelRight,
  Paperclip,
  Plus,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { AttachmentChips, textAttachmentBlock, useComposerAttachments } from "@/components/agent/composerAttachments";

import { API_BASE, api, getAuthToken, importAsset, type Asset } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { UserMessageContent, attachmentToken } from "@/features/ai-studio/userMessage";
import { MessageUsageFooter, type AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { InlineQuestions } from "@/components/agent/InlineQuestions";
import { AgentSessionSwitcher } from "@/components/agent/AgentSessionSwitcher";
import { ModelPicker } from "@/features/ai-studio/ModelPicker";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { JumpToLatest, useStickToBottom } from "@/components/agent/stickToBottom";
import { ConfirmDialog } from "@/components/app/modals";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { formatElapsedSeconds } from "@/lib/time";
import { CompactionNotice, type CompactionInfo, type ContextInfo } from "@/components/agent/ContextMeter";
import { PlanCard, type PlanStep } from "@/components/agent/PlanCard";
import { SessionSettingsMenu } from "@/components/agent/SessionSettingsMenu";
import { PANEL_HEADER_CLASS, useFloatingPanel } from "@/features/workflows/useFloatingPanel";
import { cn } from "@/lib/utils";

type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];
export type CanvasAgentMode = "docked" | "floating";


/**
 * 工作区里的常驻智能体面板 —— 工作流、创意画板和剪辑页**共用这一个**。
 *
 * 它不是第二套 AI:会话池、消息、队列、确认卡走的都是同一套 agent session。各入口的差别
 * 只有三样东西 —— 给每条消息附加的隐藏上下文、空态那句话、输入框的例子。所以这里收参数,
 * 而不是各存一份六百行的副本:副本改一处只会改好其中一个,而两边看起来一模一样。
 */
export function CanvasAgentChat({
  /** 附在每条消息上的隐藏上下文:告诉智能体它在看哪张画布、该用哪几个工具。 */
  contextLine,
  /** 空态那句话 —— 说清这个面板能干什么。 */
  emptyHint,
  placeholder,
  /** 悬浮窗几何记忆的键。**各入口各记各的**:工作流、画板、剪辑页的大小位置互不干扰。 */
  rectKey,
  workspaceId,
  mode,
  onModeChange,
  onClose,
}: {
  contextLine: string;
  emptyHint: string;
  placeholder: string;
  rectKey: string;
  workspaceId: string;
  mode: CanvasAgentMode;
  onModeChange: (mode: CanvasAgentMode) => void;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const [streamText, setStreamText] = React.useState("");
  const [streamTimeline, setStreamTimeline] = React.useState<AgentTimelineItem[]>([]);
  // 附件三种入口(选文件 / 拖放 / 粘贴)与对话页共用同一套逻辑,见 composerAttachments。
  const attach = useComposerAttachments(workspaceId);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const streamingRef = React.useRef<string | null>(null);
  const isFloating = mode === "floating";

  // 悬浮窗的拖动/缩放/位置记忆走共用 hook —— 执行历史面板用的是同一套。
  const { style: floatStyle, startDrag, handles, focusProps } = useFloatingPanel({
    storageKey: rectKey,
    floating: isFloating,
  });

  // 多会话:工作流入口复用全局 AI 会话池,只共享选中的 session id。
  const sessionKey = agentSessionSelectionKey(workspaceId);
  const sessions = useQuery({
    queryKey: ["agent-sessions", workspaceId],
    queryFn: () => api<AgentSession[]>(`/api/agent/sessions?workspace_id=${workspaceId}`),
    // 首条消息会把「新对话」自动改题,轮询让下拉里的标题跟上
    refetchInterval: 4000,
  });
  const [selectedId, setSelectedId] = React.useState<string | null>(
    () => window.localStorage.getItem(sessionKey) || null,
  );
  const sessionList = sessions.data ?? [];
  const activeSession = sessionList.find((item) => item.id === selectedId) ?? sessionList[0] ?? null;
  //: 贴底跟随(见 components/agent/stickToBottom)。此前这里是无条件 scrollTop = scrollHeight
  //: —— 用户往上翻历史会被每一次内容更新硬拽回底部。
  const stick = useStickToBottom<HTMLDivElement>(activeSession?.id);
  const sessionId = activeSession?.id ?? null;
  const switchSession = (nextId: string) => {
    if (nextId === selectedId) return;
    // 旧会话的流不许串进新视图:先掐流、清流态,再切。
    abortRef.current?.abort();
    streamingRef.current = null;
    setStreamText("");
    setStreamTimeline([]);
    setSelectedId(nextId);
    window.localStorage.setItem(sessionKey, nextId);
  };
  const clearSessionSelection = () => {
    abortRef.current?.abort();
    streamingRef.current = null;
    setStreamText("");
    setStreamTimeline([]);
    setSelectedId(null);
    window.localStorage.removeItem(sessionKey);
  };
  const newSession = useMutation({
    mutationFn: () =>
      api<AgentSession>("/api/agent/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId }),
      }),
    onSuccess: (created) => {
      // 先播种缓存再切换:等 invalidate 重拉的间隙里 selectedId 在列表里找不到,
      // 会瞬间回落到默认会话——看起来就像「点了没反应」。
      qc.setQueryData<AgentSession[]>(["agent-sessions", workspaceId], (old) => [
        created,
        ...(old ?? []).filter((item) => item.id !== created.id),
      ]);
      switchSession(created.id);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
    },
  });
  const [deletingSession, setDeletingSession] = React.useState<AgentSession | null>(null);
  const deleteSession = useMutation({
    mutationFn: (id: string) => api(`/api/agent/sessions/${id}`, { method: "DELETE" }),
    onSuccess: (_data, deletedId) => {
      setDeletingSession(null);
      const fallback = sessionList.find((item) => item.id !== deletedId) ?? null;
      qc.setQueryData<AgentSession[]>(["agent-sessions", workspaceId], (old) =>
        (old ?? []).filter((item) => item.id !== deletedId),
      );
      if (deletedId === sessionId) {
        if (fallback) switchSession(fallback.id);
        else clearSessionSelection();
      }
      qc.removeQueries({ queryKey: ["agent-messages", deletedId] });
      qc.removeQueries({ queryKey: ["agent-session", deletedId] });
      qc.removeQueries({ queryKey: ["agent-queue", deletedId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
    },
  });

  const messages = useQuery({
    queryKey: ["agent-messages", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => api<AgentMessage[]>(`/api/agent/sessions/${sessionId}/messages`),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });
  const live = useQuery({
    queryKey: ["agent-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => api<AgentSession>(`/api/agent/sessions/${sessionId}`),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });
  const running = live.data?.status === "running";
  // Same contract as the studio chat: a message typed mid-turn is a correction, the backend
  // injects it into the running turn, and one button covers stop-vs-send.
  // Same source of truth as the studio chat: the server knows what is still waiting.
  const queue = useQuery({
    queryKey: ["agent-queue", sessionId],
    enabled: Boolean(sessionId) && running,
    queryFn: () => api<AgentMessage[]>(`/api/agent/sessions/${sessionId}/queue`),
    refetchInterval: 1500,
  });
  // 计费/用量:与对话页同源,按 agent_message_id 归到各条回复(见 MessageUsageFooter)。
  const usageEvents = useQuery({
    queryKey: ["agent-usage-events", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => api<AgentUsageEvent[]>(`/api/agent/sessions/${sessionId}/usage-events`),
    refetchInterval: running ? 1200 : false,
  });
  const usageByMessage = React.useMemo(() => {
    const byMessage = new Map<string, AgentUsageEvent[]>();
    for (const event of usageEvents.data ?? []) {
      if (!event.agent_message_id) continue;
      const current = byMessage.get(event.agent_message_id) ?? [];
      current.push(event);
      byMessage.set(event.agent_message_id, current);
    }
    return byMessage;
  }, [usageEvents.data]);
  const queuedIds = new Set((running ? queue.data ?? [] : []).map((message) => message.id));

  /** 会话详情:列表接口不带水位(那要为每个会话各算一次,而界面只看当前这个)。
   *  跟着消息一起刷新 —— 一轮结束后水位就该更新。 */
  const sessionDetail = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => api<AgentSession>(`/api/agent/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
    refetchInterval: running ? 4000 : false,
  });

  /** 水位由会话详情**现算**给出,不从消息 payload 里翻。
   *  挂在消息上等于"必须先成功跑一轮才看得到" —— 而想知道"还能聊多久"的时刻恰恰在开口之前:
   *  刚打开旧会话、刚换过模型、上一轮失败了,这些时候都没有新的一轮可以带回这个数。 */
  const context = (sessionDetail.data?.context ?? null) as ContextInfo | null;

  const compact = useMutation({
    mutationFn: () => api<{ compaction: CompactionInfo | null }>(`/api/agent/sessions/${sessionId}/compact`, { method: "POST" }),
    // 压成功了对话里会多一条整理记录;没得压和压失败必须说出来,否则只是 loading 闪一下。
    onSuccess: (result) => {
      void messages.refetch();
      void sessionDetail.refetch();
      if (!result?.compaction) toast.message(t("agentCompactNothing"));
    },
    onError: (error) => toast.error(`${t("agentCompactFailed")}:${(error as Error).message}`),
  });
  const refreshQueue = () => {
    void qc.invalidateQueries({ queryKey: ["agent-queue", sessionId] });
    void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
  };
  const cancelQueued = useMutation({
    mutationFn: (messageId: string) =>
      api(`/api/agent/sessions/${sessionId}/queue/${messageId}`, { method: "DELETE" }),
    onSuccess: refreshQueue,
  });
  const steerQueued = useMutation({
    mutationFn: (messageId: string) =>
      api<{ steered: boolean }>(`/api/agent/sessions/${sessionId}/queue/${messageId}/steer`, { method: "POST" }),
    onSuccess: refreshQueue,
  });
  const showStop = running && !draft.trim() && attach.isEmpty;
  const stopTurn = useMutation({
    mutationFn: () => api(`/api/agent/sessions/${sessionId}/stop`, { method: "POST" }),
    meta: { silentError: true },
  });
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  React.useEffect(() => {
    if (!running) {
      setElapsedSeconds(0);
      return;
    }
    const startedAt = Date.now();
    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [running, sessionId]);

  // Same leak as the AI-studio chat: an unstoppable reader pins an HTTP/1.1 connection, and
  // this panel is conditionally mounted by each workspace surface, so closing it
  // mid-stream is the normal case rather than an edge one.
  const abortRef = React.useRef<AbortController | null>(null);

  const attachStream = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      streamingRef.current = targetSessionId;
      setStreamText("");
      setStreamTimeline([]);
      try {
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/agent/sessions/${targetSessionId}/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        });
        if (!response.ok || !response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const event of events) {
            const line = event.split("\n").find((item) => item.startsWith("data: "));
            if (!line) continue;
            try {
              const payload = JSON.parse(line.slice(6)) as {
                text: string;
                timeline?: AgentTimelineItem[];
              };
              if (streamingRef.current === targetSessionId) {
                setStreamText(payload.text);
                setStreamTimeline(payload.timeline ?? []);
              }
            } catch {
              // partial frame
            }
          }
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        if (streamingRef.current === targetSessionId && !controller.signal.aborted) {
          streamingRef.current = null;
          setStreamText("");
          setStreamTimeline([]);
          void qc.invalidateQueries({ queryKey: ["agent-messages", targetSessionId] });
          void qc.invalidateQueries({ queryKey: ["agent-session", targetSessionId] });
          // 回合结束后计费事件才落库,而 usage-events 只在 running 时轮询——不主动失效,这条回复
          // 的 token/费用就一直缺(见对话页同款失效)。
          void qc.invalidateQueries({ queryKey: ["agent-usage-events", targetSessionId] });
        }
      }
    },
    [qc],
  );

  React.useEffect(() => {
    if (running && sessionId && streamingRef.current !== sessionId) void attachStream(sessionId);
  }, [running, sessionId, attachStream]);

  // Close the stream on unmount — the panel is toggled open and shut routinely.
  React.useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      streamingRef.current = null;
    };
  }, []);

  const send = useMutation({
    mutationFn: async ({
      text,
      files,
      mediaAssets,
    }: {
      text: string;
      files: { name: string; content: string }[];
      mediaAssets: Asset[];
    }) => {
      // 文本文件内联为围栏上下文(纯文本智能体可读);图片/视频/音频编码成附件标记,气泡里渲染成缩略图。
      const fileBlock = textAttachmentBlock(files, t("wfAgentAttached"));
      let visibleContent = text || files.map((file) => `[${t("wfAgentAttached")} ${file.name}]`).join("\n");
      for (const asset of mediaAssets) visibleContent += attachmentToken(asset);
      visibleContent = visibleContent.trim();
      const context = [contextLine, fileBlock].filter(Boolean).join("\n\n");
      let targetId = sessionId;
      if (!targetId) {
        const created = await api<AgentSession>("/api/agent/sessions", {
          method: "POST",
          body: JSON.stringify({ workspace_id: workspaceId }),
        });
        qc.setQueryData<AgentSession[]>(["agent-sessions", workspaceId], (old) => [
          created,
          ...(old ?? []).filter((item) => item.id !== created.id),
        ]);
        switchSession(created.id);
        targetId = created.id;
      }
      const message = await api<AgentMessage>(`/api/agent/sessions/${targetId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: visibleContent, context }),
      });
      return { message, targetId };
    },
    onSuccess: ({ targetId }) => {
      setDraft("");
      attach.clear();
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
      void attachStream(targetId);
    },
  });

  const submit = () => {
    // `running` is deliberately not a guard: the backend steers a mid-turn message.
    if ((!draft.trim() && attach.isEmpty) || send.isPending) return;
    send.mutate({ text: draft.trim(), files: attach.files, mediaAssets: attach.media });
  };

  return (
    <aside
      className={cn(
        "grid grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-panel",
        isFloating
          ? "fixed min-h-[380px] min-w-[320px] max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)] rounded-lg border border-border-strong"
          : "relative z-[1] h-full w-full min-h-0 min-w-0 border-0 shadow-none",
      )}
      style={floatStyle}
      {...focusProps}
      role={isFloating ? "dialog" : "complementary"}
      aria-label={t("wfAgentTitle")}
    >
      {handles}
      <div className={cn(PANEL_HEADER_CLASS, isFloating && "cursor-move")} onPointerDown={startDrag}>
        <h2
          className="min-w-0"
          data-no-drag
          onPointerDown={(event) => event.stopPropagation()}
        >
          <AgentSessionSwitcher
            sessions={sessionList}
            activeSession={activeSession}
            deleting={deleteSession.isPending}
            onSelect={switchSession}
            onDelete={setDeletingSession}
          />
        </h2>
        <button
          type="button"
          className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
          aria-label={t("wfAgentNewSession")}
          title={t("wfAgentNewSession")}
          disabled={newSession.isPending}
          onClick={() => newSession.mutate()}
        >
          <Plus size={13} />
        </button>
        <button
          type="button"
          className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive ml-auto"
          aria-label={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          title={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          onClick={() => onModeChange(isFloating ? "docked" : "floating")}
        >
          {isFloating ? <PanelRight size={13} /> : <Move size={13} />}
        </button>
        <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive" aria-label={t("close")} onClick={onClose}>
          <X size={13} />
        </button>
      </div>
      <div className="relative grid min-h-0 min-w-0">
      <div
        className={cn(
          // 横向必须一起锁死。grid 子项默认 min-width:auto —— 一段长代码块 / 一条长 URL 会把
          // 整列撑宽,于是整个助手面板可以左右滚,正文跟着晃。grid-cols 显式给 minmax(0,1fr)
          // 才让子项允许被压缩,overflow-x-hidden 兜住越界的那一点。
          // (代码块自己有 overflow-x-auto,但那只在父容器被约束时才生效。)
          "grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-y-auto overflow-x-hidden p-2.5",
          (messages.data ?? []).length === 0 && !running && "content-center justify-items-center",
        )}
        ref={stick.ref}
      >
        {(messages.data ?? []).length === 0 && !running && (
          <div className="grid justify-items-center gap-1.5 p-2.5 text-center text-xs text-muted-foreground [&_svg]:text-primary [&_svg]:opacity-70">
            <Bot size={16} />
            <span>{emptyHint}</span>
          </div>
        )}
        {(messages.data ?? []).map((message) => {
          const payload = message.payload as
            | { usage?: { duration_seconds?: number }; timeline?: AgentTimelineItem[]; compaction?: CompactionInfo }
            | null;
          const duration = payload?.usage?.duration_seconds;
          if (queuedIds.has(message.id)) return null;
          // 手动压缩留下的是一条 role=system、内容为空的消息:它只承载压缩标记。
          if (message.role === "system") {
            return payload?.compaction ? <CompactionNotice key={message.id} info={payload.compaction} /> : null;
          }
          return (
            <div
              key={message.id}
              className={
                message.role === "assistant"
                  ? "relative w-full min-w-0 max-w-full text-ui-md leading-[1.65] [word-break:break-word]"
                  : "ml-auto mr-0 w-fit min-w-0 max-w-[min(560px,88%)] justify-self-end whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]"
              }
            >
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
                <UserMessageContent content={message.content} />
              )}
              {message.role === "assistant" && (
                <MessageUsageFooter
                  content={message.content}
                  usageEvents={usageByMessage.get(message.id) ?? []}
                  durationOverride={duration}
                  className="flex-wrap text-muted-foreground"
                />
              )}
            </div>
          );
        })}
        {running && streamText && (
          <div className="relative w-full min-w-0 max-w-full text-ui-md leading-[1.65] [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <div className="mt-1.5 flex min-h-[18px] items-center gap-1.5 text-muted-foreground">
              <Loader2 size={11} className="animate-openstudio-spin" />
              <span className="timecode text-ui-xs text-muted-foreground">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </div>
          </div>
        )}
        {running && !streamText && (
          <div className="relative flex w-full min-w-0 max-w-full flex-col items-stretch gap-1.5 text-ui-md leading-[1.65] text-muted-foreground [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <Loader2 size={12} className="animate-openstudio-spin" /> {t("chatThinking")}
              <span className="timecode text-ui-xs text-muted-foreground">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </span>
          </div>
        )}
        {activeSession && <InlineConfirmations workspaceId={workspaceId} allowKey={activeSession.id} />}
              {activeSession && <InlineQuestions sessionId={activeSession.id} />}
      </div>
      <JumpToLatest stick={stick} label={t("chatJumpToLatest")} newLabel={t("chatNewBelow")} />
      </div>
      {(queue.data ?? []).map((message) => (
        <div
          className="mx-auto mb-1.5 flex w-full max-w-[780px] items-center gap-2 rounded-lg border border-border bg-panel px-2.5 py-[7px] text-xs"
          key={message.id}
        >
          <CornerDownRight size={12} className="shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-foreground" title={message.content}>
            {message.content}
          </span>
          <button
            type="button"
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-ui-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            disabled={steerQueued.isPending}
            onClick={() => steerQueued.mutate(message.id)}
            title={t("chatSteerHint")}
          >
            <CornerDownRight size={11} /> {t("chatSteerAction")}
          </button>
          <button
            type="button"
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-ui-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            disabled={cancelQueued.isPending}
            onClick={() => cancelQueued.mutate(message.id)}
            aria-label={t("chatQueuedCancel")}
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      <AttachmentChips attachments={attach} />
      <div className="mx-2 mb-2 mt-2 flex flex-col gap-0.5 rounded-[20px] border border-border bg-panel px-2 pb-1.5 pt-2 transition-[border-color] duration-100 focus-within:border-ring">
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            void attach.accept(event.target.files);
            event.target.value = "";
          }}
        />
        {/* 内层去底色/边框/焦点环:外层输入卡已是表面,双层盒子叠着难看(对话页同款处理)。 */}
        <Textarea
          rows={1}
          className="max-h-[220px] min-h-9 w-full min-w-0 resize-none border-0 bg-transparent px-0.5 pb-1.5 pt-0.5 text-ui-md leading-[1.55] shadow-none outline-none placeholder:text-muted-foreground placeholder:opacity-100 focus-visible:ring-0"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onPaste={attach.onPaste}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex min-w-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              aria-label={t("wfAgentAttach")}
              title={t("wfAgentAttach")}
              onClick={() => fileRef.current?.click()}
            >
              <Paperclip size={15} />
            </Button>
            <ModelPicker workspaceId={workspaceId} session={activeSession} />
            {/* 与 AI Studio 用同一个组件:此前两边各写各的工具行,同一个功能的位置、顺序、
                有无都不一致。工作流助手不做素材分析,那一项在这里是死的,关掉。 */}
            <SessionSettingsMenu
              session={sessionDetail.data ?? null}
              context={context}
              compacting={compact.isPending}
              onCompact={running ? undefined : () => compact.mutate()}
              showAnalysis={false}
            />
          </div>
          {showStop ? (
            <Button
              size="icon"
              className="rounded-full"
              aria-label={t("chatStop")}
              loading={stopTurn.isPending}
              onClick={() => stopTurn.mutate()}
            >
              <Square size={12} fill="currentColor" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="rounded-full"
              aria-label={running ? t("chatSteer") : t("chatSend")}
              disabled={(!draft.trim() && attach.isEmpty) || attach.uploading} loading={send.isPending}
              onClick={submit}
            >
              <Send size={14} />
            </Button>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={deletingSession !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteSessionBody")}
        onCancel={() => setDeletingSession(null)}
        onConfirm={() => deletingSession && deleteSession.mutate(deletingSession.id)}
      />
    </aside>
  );
}
