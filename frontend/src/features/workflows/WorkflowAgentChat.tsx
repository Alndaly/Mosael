import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  ChevronDown,
  CornerDownRight,
  GripHorizontal,
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

import { API_BASE, api, getAuthToken, importAsset, type Asset } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { UserMessageContent, attachmentToken } from "@/features/ai-studio/userMessage";
import { MessageUsageFooter, type AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { ModelPicker } from "@/features/ai-studio/ModelPicker";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { ConfirmDialog } from "@/components/app/modals";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { formatElapsedSeconds } from "@/lib/time";
import { useFloatingPanel } from "@/features/workflows/useFloatingPanel";
import { cn } from "@/lib/utils";

type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];
export type WorkflowAgentMode = "docked" | "floating";

/** 悬浮窗几何记忆的键。v2:默认尺寸加大 + 八向缩放手柄(升键让老用户的小窗让位一次)。 */
const RECT_KEY = "openstudio.wf.agent.rect.v2";


/**
 * 工作流常驻智能体面板:它不是第二套 AI,而是全局 AI 助手的工作流入口。
 * 会话池/消息/队列/确认卡都走同一套 agent session;入口只给每条消息附加
 * 当前 workflow_id/name 的隐藏上下文。
 */
export function WorkflowAgentChat({
  workflowId,
  workflowName,
  workspaceId,
  mode,
  onModeChange,
  onClose,
}: {
  workflowId: string;
  workflowName: string;
  workspaceId: string;
  mode: WorkflowAgentMode;
  onModeChange: (mode: WorkflowAgentMode) => void;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const [streamText, setStreamText] = React.useState("");
  const [streamTimeline, setStreamTimeline] = React.useState<AgentTimelineItem[]>([]);
  const [attachments, setAttachments] = React.useState<{ name: string; content: string }[]>([]);
  const [media, setMedia] = React.useState<Asset[]>([]);
  const [uploading, setUploading] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const MAX_FILE = 200 * 1024; // 200KB of text
  // 图片/视频/音频走素材导入(智能体可分析,与对话页一致);文本文件仍内联为上下文(便于按脚本搭流程)。
  const pickFiles = async (files: FileList | null) => {
    if (!files) return;
    const added: { name: string; content: string }[] = [];
    for (const file of Array.from(files)) {
      if (/^(image|video|audio)\//.test(file.type)) {
        setUploading(true);
        try {
          const asset = await importAsset({ workspaceId, file });
          setMedia((cur) => [...cur, asset]);
        } catch {
          toast.error(t("wfAgentFileUnreadable").replace("{name}", file.name));
        } finally {
          setUploading(false);
        }
        continue;
      }
      if (file.size > MAX_FILE) {
        toast.error(t("wfAgentFileTooBig").replace("{name}", file.name));
        continue;
      }
      try {
        added.push({ name: file.name, content: await file.text() });
      } catch {
        toast.error(t("wfAgentFileUnreadable").replace("{name}", file.name));
      }
    }
    if (added.length) setAttachments((cur) => [...cur, ...added]);
  };
  const streamingRef = React.useRef<string | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);
  const isFloating = mode === "floating";

  // 悬浮窗的拖动/缩放/位置记忆走共用 hook —— 执行历史面板用的是同一套。
  const { style: floatStyle, startDrag, handles } = useFloatingPanel({
    storageKey: RECT_KEY,
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
  const [sessionMenuOpen, setSessionMenuOpen] = React.useState(false);
  const sessionList = sessions.data ?? [];
  const activeSession = sessionList.find((item) => item.id === selectedId) ?? sessionList[0] ?? null;
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
  const showStop = running && !draft.trim() && attachments.length === 0 && media.length === 0;
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
  // this panel is conditionally mounted ({agentOpen && <WorkflowAgentChat/>}), so closing it
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

  React.useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.data?.length, streamText]);

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
      const fileBlock = files.map((f) => `[${t("wfAgentAttached")} ${f.name}]\n\`\`\`\n${f.content}\n\`\`\``).join("\n\n");
      let visibleContent = text || files.map((file) => `[${t("wfAgentAttached")} ${file.name}]`).join("\n");
      for (const asset of mediaAssets) visibleContent += attachmentToken(asset);
      visibleContent = visibleContent.trim();
      const context = [
        t("wfAgentContext").replace("{id}", workflowId).replace("{name}", workflowName),
        fileBlock,
      ].filter(Boolean).join("\n\n");
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
      setAttachments([]);
      setMedia([]);
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
      void attachStream(targetId);
    },
  });

  const submit = () => {
    // `running` is deliberately not a guard: the backend steers a mid-turn message.
    if ((!draft.trim() && attachments.length === 0 && media.length === 0) || send.isPending) return;
    send.mutate({ text: draft.trim(), files: attachments, mediaAssets: media });
  };

  return (
    <aside
      className={cn(
        "grid grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-border-strong bg-panel",
        isFloating
          ? "fixed z-[55] min-h-[380px] min-w-[320px] max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)]"
          : "relative z-[1] h-full w-full min-h-0 min-w-0 rounded-lg border-border shadow-none",
      )}
      style={floatStyle}
      role={isFloating ? "dialog" : "complementary"}
      aria-label={t("wfAgentTitle")}
    >
      {handles}
      <div className={cn("flex cursor-default select-none touch-none items-center gap-1.5 border-b border-border py-1.5 pl-2.5 pr-2 [&_h2]:m-0 [&_h2]:text-[12.5px] [&_h2]:font-semibold", isFloating && "cursor-move")} onPointerDown={startDrag}>
        <h2 className="inline-flex items-center gap-1.5">
          <Bot size={14} /> {t("wfAgentTitle")}
        </h2>
        {sessionList.length > 0 && sessionId && (
          <span data-no-drag onPointerDown={(event) => event.stopPropagation()}>
            <Popover open={sessionMenuOpen} onOpenChange={setSessionMenuOpen}>
              <PopoverTrigger asChild>
                <button type="button" className="inline-flex h-6 min-w-0 max-w-[150px] cursor-pointer items-center justify-between gap-1.5 rounded-lg border border-border bg-panel px-2 text-xs text-foreground hover:border-border-strong [&>span]:truncate [&_svg]:shrink-0 [&_svg]:text-muted-foreground" aria-label={t("wfAgentSessions")}>
                  <span>{activeSession?.title ?? t("wfAgentSessions")}</span>
                  <ChevronDown size={12} />
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="z-[120] max-h-[min(320px,var(--radix-popover-content-available-height))] w-[min(360px,calc(100vw-32px))] overflow-y-auto p-1.5 shadow-[var(--shadow-raised)]"
                aria-label={t("wfAgentSessions")}
                onPointerDown={(event) => event.stopPropagation()}
              >
                {sessionList.map((item) => (
                  <div
                    key={item.id}
                    className={cn(
                    "grid grid-cols-[minmax(0,1fr)_28px] items-center gap-1 rounded-lg hover:bg-secondary",
                    item.id === sessionId && "bg-secondary",
                  )}
                  >
                    <button
                      type="button"
                      className="flex min-w-0 cursor-pointer items-center justify-between gap-2.5 border-0 bg-transparent py-2 pl-2.5 pr-2 text-left text-[13px] text-inherit [&_span]:min-w-0 [&_span]:truncate [&_svg]:shrink-0 [&_svg]:text-primary"
                      onClick={() => {
                        setSessionMenuOpen(false);
                        switchSession(item.id);
                      }}
                    >
                      <span>{item.title}</span>
                      {item.id === sessionId && <Check size={13} />}
                    </button>
                    <button
                      type="button"
                      className="inline-flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] hover:text-destructive disabled:cursor-default disabled:opacity-45"
                      aria-label={t("delete")}
                      title={t("delete")}
                      disabled={deleteSession.isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSessionMenuOpen(false);
                        setDeletingSession(item);
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </PopoverContent>
            </Popover>
          </span>
        )}
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
        {isFloating && <GripHorizontal size={13} className="text-muted-foreground opacity-60" />}
        <button type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive" aria-label={t("close")} onClick={onClose}>
          <X size={13} />
        </button>
      </div>
      <div
        className={cn(
          "grid min-h-0 content-start gap-2 overflow-y-auto p-2.5",
          (messages.data ?? []).length === 0 && !running && "content-center justify-items-center",
        )}
        ref={threadRef}
      >
        {(messages.data ?? []).length === 0 && !running && (
          <div className="grid justify-items-center gap-1.5 p-2.5 text-center text-xs text-muted-foreground [&_svg]:text-primary [&_svg]:opacity-70">
            <Bot size={16} />
            <span>{t("wfAgentEmpty")}</span>
          </div>
        )}
        {(messages.data ?? []).map((message) => {
          const payload = message.payload as { usage?: { duration_seconds?: number }; timeline?: AgentTimelineItem[] } | null;
          const duration = payload?.usage?.duration_seconds;
          if (queuedIds.has(message.id)) return null;
          return (
            <div
              key={message.id}
              className={
                message.role === "assistant"
                  ? "relative w-full min-w-0 max-w-full text-[13.5px] leading-[1.65] [word-break:break-word]"
                  : "ml-auto mr-0 w-fit min-w-0 max-w-[min(560px,88%)] justify-self-end whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-[13.5px] leading-[1.65] text-foreground [word-break:break-word]"
              }
            >
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
          <div className="relative w-full min-w-0 max-w-full text-[13.5px] leading-[1.65] [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <div className="mt-1.5 flex min-h-[18px] items-center gap-1.5 text-muted-foreground">
              <Loader2 size={11} className="animate-openstudio-spin" />
              <span className="timecode text-[11px] text-muted-foreground">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </div>
          </div>
        )}
        {running && !streamText && (
          <div className="relative flex w-full min-w-0 max-w-full flex-col items-stretch gap-1.5 text-[13.5px] leading-[1.65] text-muted-foreground [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <Loader2 size={12} className="animate-openstudio-spin" /> {t("chatThinking")}
              <span className="timecode text-[11px] text-muted-foreground">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </span>
          </div>
        )}
        {activeSession && <InlineConfirmations workspaceId={workspaceId} allowKey={activeSession.id} />}
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
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => steerQueued.mutate(message.id)}
            title={t("chatSteerHint")}
          >
            <CornerDownRight size={11} /> {t("chatSteerAction")}
          </button>
          <button
            type="button"
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => cancelQueued.mutate(message.id)}
            aria-label={t("chatQueuedCancel")}
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      {(attachments.length > 0 || media.length > 0 || uploading) && (
        <div className="flex flex-wrap gap-1 px-3.5 pt-1">
          {media.map((asset, i) => (
            <span key={asset.id} className="inline-flex max-w-40 items-center gap-1 rounded-md border border-border bg-[rgb(255_255_255/0.07)] py-0.5 pl-1.5 pr-1 text-[11px] text-foreground [&_button]:inline-flex [&_button]:text-muted-foreground [&_button:hover]:text-foreground" title={asset.name}>
              <Paperclip size={11} />
              <span className="truncate">{asset.name}</span>
              <button
                type="button"
                aria-label={t("close")}
                onClick={() => setMedia((cur) => cur.filter((_, j) => j !== i))}
              >
                <X size={11} />
              </button>
            </span>
          ))}
          {attachments.map((file, i) => (
            <span key={`${file.name}-${i}`} className="inline-flex max-w-40 items-center gap-1 rounded-md border border-border bg-[rgb(255_255_255/0.07)] py-0.5 pl-1.5 pr-1 text-[11px] text-foreground [&_button]:inline-flex [&_button]:text-muted-foreground [&_button:hover]:text-foreground" title={file.name}>
              <Paperclip size={11} />
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                aria-label={t("close")}
                onClick={() => setAttachments((cur) => cur.filter((_, j) => j !== i))}
              >
                <X size={11} />
              </button>
            </span>
          ))}
          {uploading && (
            <span className="inline-flex items-center gap-1 rounded-md border border-border bg-[rgb(255_255_255/0.07)] px-1.5 py-0.5 text-[11px] text-muted-foreground">
              <Loader2 size={11} className="animate-openstudio-spin" /> {t("wfAgentAttach")}
            </span>
          )}
        </div>
      )}
      <div className="mx-2 mb-2 mt-2 flex flex-col gap-0.5 rounded-[20px] border border-border bg-panel px-2 pb-1.5 pt-2 transition-[border-color] duration-100 focus-within:border-ring">
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            void pickFiles(event.target.files);
            event.target.value = "";
          }}
        />
        {/* 内层去底色/边框/焦点环:外层输入卡已是表面,双层盒子叠着难看(对话页同款处理)。 */}
        <Textarea
          rows={1}
          className="max-h-[220px] min-h-9 w-full min-w-0 resize-none border-0 bg-transparent px-0.5 pb-1.5 pt-0.5 text-[13.5px] leading-[1.55] shadow-none outline-none placeholder:text-muted-foreground placeholder:opacity-100 focus-visible:ring-0"
          value={draft}
          placeholder={t("wfAgentPlaceholder")}
          onChange={(event) => setDraft(event.target.value)}
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
          </div>
          {showStop ? (
            <Button
              size="icon"
              className="rounded-full"
              aria-label={t("chatStop")}
              onClick={() => stopTurn.mutate()}
            >
              <Square size={12} fill="currentColor" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="rounded-full"
              aria-label={running ? t("chatSteer") : t("chatSend")}
              disabled={(!draft.trim() && attachments.length === 0 && media.length === 0) || send.isPending || uploading}
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
