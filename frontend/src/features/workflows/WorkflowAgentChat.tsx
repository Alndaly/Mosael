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

import { API_BASE, api, getAuthToken } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { ConfirmDialog } from "@/components/ui/modals";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { formatElapsedSeconds } from "@/lib/time";

type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];
export type WorkflowAgentMode = "docked" | "floating";

// v2:默认尺寸加大 + 八向缩放手柄。升键让老用户存下的 320×460 小窗让位给新默认(仅一次)。
const RECT_KEY = "mibu.wf.agent.rect.v2";

interface FloatRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const MIN_W = 320;
const MIN_H = 380;

function clampRect(rect: FloatRect): FloatRect {
  const w = Math.min(Math.max(rect.w, MIN_W), window.innerWidth - 24);
  const h = Math.min(Math.max(rect.h, MIN_H), window.innerHeight - 24);
  return {
    w,
    h,
    x: Math.min(Math.max(rect.x, 8), window.innerWidth - w - 8),
    y: Math.min(Math.max(rect.y, 8), window.innerHeight - 60),
  };
}

function defaultRect(): FloatRect {
  // 随视口取,小屏不顶满、大屏不寒酸;落位右下角。
  const w = Math.min(480, window.innerWidth - 48);
  const h = Math.min(640, window.innerHeight - 96);
  return { x: window.innerWidth - w - 20, y: window.innerHeight - h - 44, w, h };
}

function loadRect(): FloatRect {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECT_KEY) ?? "");
    return clampRect({ x: Number(parsed.x), y: Number(parsed.y), w: Number(parsed.w), h: Number(parsed.h) });
  } catch {
    return clampRect(defaultRect());
  }
}

/** 八向缩放:每个手柄声明它拉动哪几条边。 */
const RESIZE_EDGES = ["n", "s", "e", "w", "ne", "nw", "se", "sw"] as const;
type ResizeEdge = (typeof RESIZE_EDGES)[number];

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
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const MAX_FILE = 200 * 1024; // 200KB of text
  const pickFiles = async (files: FileList | null) => {
    if (!files) return;
    const added: { name: string; content: string }[] = [];
    for (const file of Array.from(files)) {
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

  // 悬浮窗:标题栏拖动 + 原生右下角缩放,位置尺寸记忆。
  const [rect, setRect] = React.useState<FloatRect>(loadRect);
  const panelRef = React.useRef<HTMLElement | null>(null);
  const persistRect = React.useCallback((next: FloatRect) => {
    window.localStorage.setItem(RECT_KEY, JSON.stringify(next));
  }, []);

  const startDrag = (event: React.PointerEvent) => {
    if (!isFloating) return;
    if ((event.target as HTMLElement).closest("button,input,textarea,a,[role='combobox'],[data-no-drag]")) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...rect };
    const onMove = (moveEvent: PointerEvent) => {
      setRect(clampRect({ ...origin, x: origin.x + (moveEvent.clientX - startX), y: origin.y + (moveEvent.clientY - startY) }));
    };
    const onUp = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      persistRect(clampRect({ ...origin, x: origin.x + (upEvent.clientX - startX), y: origin.y + (upEvent.clientY - startY) }));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // 八向缩放:拖 n/w 边时同步移动 x/y(锚定对边),clampRect 统一夹取。
  // 用自定义手柄而不是原生 resize: both——原生只有右下一个不显眼的小角,
  // 且在 position: fixed + 手动定位下无法向上/向左扩展。
  const startResize = (edge: ResizeEdge) => (event: React.PointerEvent) => {
    if (!isFloating) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...rect };
    const apply = (clientX: number, clientY: number): FloatRect => {
      const dx = clientX - startX;
      const dy = clientY - startY;
      let { x, y, w, h } = origin;
      if (edge.includes("e")) w = origin.w + dx;
      if (edge.includes("s")) h = origin.h + dy;
      if (edge.includes("w")) {
        w = Math.min(Math.max(origin.w - dx, MIN_W), origin.x + origin.w - 8);
        x = origin.x + origin.w - w;
      }
      if (edge.includes("n")) {
        h = Math.min(Math.max(origin.h - dy, MIN_H), origin.y + origin.h - 8);
        y = origin.y + origin.h - h;
      }
      return clampRect({ x, y, w, h });
    };
    const onMove = (moveEvent: PointerEvent) => setRect(apply(moveEvent.clientX, moveEvent.clientY));
    const onUp = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      persistRect(apply(upEvent.clientX, upEvent.clientY));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

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
  const showStop = running && !draft.trim() && attachments.length === 0;
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
    mutationFn: async ({ text, files }: { text: string; files: { name: string; content: string }[] }) => {
      // Attached files are inlined as fenced context so the text-only agent can read them.
      const fileBlock = files.map((f) => `[${t("wfAgentAttached")} ${f.name}]\n\`\`\`\n${f.content}\n\`\`\``).join("\n\n");
      const visibleContent = text || files.map((file) => `[${t("wfAgentAttached")} ${file.name}]`).join("\n");
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
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
      void attachStream(targetId);
    },
  });

  const submit = () => {
    // `running` is deliberately not a guard: the backend steers a mid-turn message.
    if ((!draft.trim() && attachments.length === 0) || send.isPending) return;
    send.mutate({ text: draft.trim(), files: attachments });
  };

  return (
    <aside
      ref={panelRef}
      className={`wf-agent wf-agent-${mode}`}
      style={isFloating ? { left: rect.x, top: rect.y, width: rect.w, height: rect.h } : undefined}
      role={isFloating ? "dialog" : "complementary"}
      aria-label={t("wfAgentTitle")}
    >
      {isFloating &&
        RESIZE_EDGES.map((edge) => (
          <div key={edge} className={`wf-agent-rs wf-agent-rs-${edge}`} onPointerDown={startResize(edge)} />
        ))}
      <div className="wf-agent-head" onPointerDown={startDrag}>
        <h2 className="wf-agent-title">
          <Bot size={14} /> {t("wfAgentTitle")}
        </h2>
        {sessionList.length > 0 && sessionId && (
          <span data-no-drag onPointerDown={(event) => event.stopPropagation()}>
            <Popover open={sessionMenuOpen} onOpenChange={setSessionMenuOpen}>
              <PopoverTrigger asChild>
                <button type="button" className="wf-agent-session-picker" aria-label={t("wfAgentSessions")}>
                  <span>{activeSession?.title ?? t("wfAgentSessions")}</span>
                  <ChevronDown size={12} />
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="wf-agent-session-menu"
                aria-label={t("wfAgentSessions")}
                onPointerDown={(event) => event.stopPropagation()}
              >
                {sessionList.map((item) => (
                  <div
                    key={item.id}
                    className={item.id === sessionId ? "wf-agent-session-row active" : "wf-agent-session-row"}
                  >
                    <button
                      type="button"
                      className="wf-agent-session-main"
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
                      className="wf-agent-session-row-delete"
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
          className="inspector-delete"
          aria-label={t("wfAgentNewSession")}
          title={t("wfAgentNewSession")}
          disabled={newSession.isPending}
          onClick={() => newSession.mutate()}
        >
          <Plus size={13} />
        </button>
        <button
          type="button"
          className="inspector-delete wf-agent-mode-toggle"
          aria-label={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          title={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
          onClick={() => onModeChange(isFloating ? "docked" : "floating")}
        >
          {isFloating ? <PanelRight size={13} /> : <Move size={13} />}
        </button>
        {isFloating && <GripHorizontal size={13} className="wf-agent-grip" />}
        <button type="button" className="inspector-delete" aria-label={t("close")} onClick={onClose}>
          <X size={13} />
        </button>
      </div>
      <div className="wf-agent-thread" ref={threadRef}>
        {(messages.data ?? []).length === 0 && !running && (
          <div className="wf-agent-empty">
            <Bot size={16} />
            <span>{t("wfAgentEmpty")}</span>
          </div>
        )}
        {(messages.data ?? []).map((message) => {
          const payload = message.payload as { usage?: { duration_seconds?: number }; timeline?: AgentTimelineItem[] } | null;
          const duration = payload?.usage?.duration_seconds;
          if (queuedIds.has(message.id)) return null;
          return (
            <div key={message.id} className={`wf-agent-msg chat-bubble ${message.role}`}>
              {message.role === "assistant" ? (
                message.error ? (
                  <AgentErrorCard content={message.content} error={message.error} />
                ) : (
                  <AgentTurnContent timeline={payload?.timeline} />
                )
              ) : (
                <div className="chat-bubble-content">{message.content}</div>
              )}
              {message.role === "assistant" && typeof duration === "number" && (
                <div className="chat-msg-meta live">
                  <span className="chat-msg-duration timecode">
                    {t("usageDuration").replace("{t}", formatElapsedSeconds(duration))}
                  </span>
                </div>
              )}
            </div>
          );
        })}
        {running && streamText && (
          <div className="wf-agent-msg chat-bubble assistant streaming">
            <AgentTurnContent timeline={streamTimeline} />
            <div className="chat-msg-meta live">
              <Loader2 size={11} className="spin" />
              <span className="chat-msg-duration timecode">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </div>
          </div>
        )}
        {running && !streamText && (
          <div className="wf-agent-msg chat-bubble assistant thinking">
            <AgentTurnContent timeline={streamTimeline} />
            <span className="wf-agent-thinking-row">
              <Loader2 size={12} className="spin" /> {t("chatThinking")}
              <span className="chat-msg-duration timecode">
                {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
              </span>
            </span>
          </div>
        )}
        {activeSession && <InlineConfirmations workspaceId={workspaceId} allowKey={activeSession.id} />}
      </div>
      {(queue.data ?? []).map((message) => (
        <div className="chat-pending" key={message.id}>
          <CornerDownRight size={12} className="chat-pending-icon" />
          <span className="chat-pending-text" title={message.content}>
            {message.content}
          </span>
          <button
            type="button"
            className="chat-pending-action"
            onClick={() => steerQueued.mutate(message.id)}
            title={t("chatSteerHint")}
          >
            <CornerDownRight size={11} /> {t("chatSteerAction")}
          </button>
          <button
            type="button"
            className="chat-pending-action"
            onClick={() => cancelQueued.mutate(message.id)}
            aria-label={t("chatQueuedCancel")}
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      {attachments.length > 0 && (
        <div className="wf-agent-attachments">
          {attachments.map((file, i) => (
            <span key={`${file.name}-${i}`} className="wf-agent-chip" title={file.name}>
              <Paperclip size={11} />
              <span className="wf-agent-chip-name">{file.name}</span>
              <button
                type="button"
                aria-label={t("close")}
                onClick={() => setAttachments((cur) => cur.filter((_, j) => j !== i))}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="wf-agent-composer">
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
        <Textarea
          rows={1}
          value={draft}
          placeholder={t("wfAgentPlaceholder")}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="wf-agent-actions">
          <Button
            variant="ghost"
            size="icon-sm"
            className="wf-agent-attach"
            aria-label={t("wfAgentAttach")}
            title={t("wfAgentAttach")}
            onClick={() => fileRef.current?.click()}
          >
            <Paperclip size={15} />
          </Button>
          {showStop ? (
            <Button
              size="icon-sm"
              className="wf-agent-send"
              aria-label={t("chatStop")}
              onClick={() => stopTurn.mutate()}
            >
              <Square size={12} fill="currentColor" />
            </Button>
          ) : (
            <Button
              size="icon-sm"
              className="wf-agent-send"
              aria-label={running ? t("chatSteer") : t("chatSend")}
              disabled={(!draft.trim() && attachments.length === 0) || send.isPending}
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
