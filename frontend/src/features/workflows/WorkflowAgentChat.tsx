import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, GripHorizontal, Loader2, Paperclip, Send, X } from "lucide-react";
import { Streamdown } from "streamdown";
import { toast } from "sonner";

import { API_BASE, api, getAuthToken, workflowAgentSession } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { AgentErrorCard, ToolCalls, type ToolCall } from "@/components/agent/ToolCalls";

type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];

const RECT_KEY = "mibu.wf.agent.rect";

interface FloatRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function clampRect(rect: FloatRect): FloatRect {
  const w = Math.min(Math.max(rect.w, 280), window.innerWidth - 24);
  const h = Math.min(Math.max(rect.h, 320), window.innerHeight - 24);
  return {
    w,
    h,
    x: Math.min(Math.max(rect.x, 8), window.innerWidth - w - 8),
    y: Math.min(Math.max(rect.y, 8), window.innerHeight - 60),
  };
}

function loadRect(): FloatRect {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECT_KEY) ?? "");
    return clampRect({ x: Number(parsed.x), y: Number(parsed.y), w: Number(parsed.w), h: Number(parsed.h) });
  } catch {
    return clampRect({ x: window.innerWidth - 356, y: window.innerHeight - 520, w: 320, h: 460 });
  }
}

/**
 * 工作流常驻智能体面板:每个工作流绑定一个 agent 会话(external_key),
 * 记忆随会话长期保留(adapter --resume)。智能体通过 MCP 的
 * get_workflow / update_workflow 读改图 —— 改动走确认卡,批准后
 * 画布自动刷新。
 */
export function WorkflowAgentChat({
  workflowId,
  workflowName,
  onClose,
}: {
  workflowId: string;
  workflowName: string;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const [streamText, setStreamText] = React.useState("");
  const [streamTools, setStreamTools] = React.useState<ToolCall[]>([]);
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

  // 悬浮窗:标题栏拖动 + 原生右下角缩放,位置尺寸记忆。
  const [rect, setRect] = React.useState<FloatRect>(loadRect);
  const panelRef = React.useRef<HTMLElement | null>(null);
  const persistRect = React.useCallback((next: FloatRect) => {
    window.localStorage.setItem(RECT_KEY, JSON.stringify(next));
  }, []);

  const startDrag = (event: React.PointerEvent) => {
    if ((event.target as HTMLElement).closest("button")) return;
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

  // 原生 resize 改变的是元素盒子,观察后同步回状态并持久化。
  React.useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.borderBoxSize?.[0];
      if (!box) return;
      setRect((current) => {
        const next = clampRect({ ...current, w: Math.round(box.inlineSize), h: Math.round(box.blockSize) });
        persistRect(next);
        return next;
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [persistRect]);

  const session = useQuery({
    queryKey: ["workflow-agent-session", workflowId],
    queryFn: () => workflowAgentSession(workflowId),
    staleTime: Infinity,
  });
  const sessionId = session.data?.id ?? null;

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
              const payload = JSON.parse(line.slice(6)) as { text: string; tools?: ToolCall[] };
              if (streamingRef.current === targetSessionId) {
                setStreamText(payload.text);
                setStreamTools(payload.tools ?? []);
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
          setStreamTools([]);
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
      const body = fileBlock ? (text ? `${fileBlock}\n\n${text}` : fileBlock) : text;
      // 首条消息带上工作流上下文,智能体后续靠会话记忆 + MCP 工具工作。
      const isFirst = (messages.data ?? []).length === 0;
      const finalContent = isFirst
        ? `${t("wfAgentContext").replace("{id}", workflowId).replace("{name}", workflowName)}\n\n${body}`
        : body;
      return api<AgentMessage>(`/api/agent/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: finalContent }),
      });
    },
    onSuccess: () => {
      setDraft("");
      setAttachments([]);
      void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
      if (sessionId) void attachStream(sessionId);
    },
  });

  const submit = () => {
    if ((!draft.trim() && attachments.length === 0) || !sessionId || running || send.isPending) return;
    send.mutate({ text: draft.trim(), files: attachments });
  };

  return (
    <aside
      ref={panelRef}
      className="wf-agent"
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
      role="dialog"
      aria-label={t("wfAgentTitle")}
    >
      <div className="wf-agent-head" onPointerDown={startDrag}>
        <h2 className="wf-agent-title">
          <Bot size={14} /> {t("wfAgentTitle")}
        </h2>
        <GripHorizontal size={13} className="wf-agent-grip" />
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
          const payload = message.payload as { tools?: ToolCall[] } | null;
          return (
            <div key={message.id} className={`wf-agent-msg ${message.role}`}>
              {message.role === "assistant" && <ToolCalls tools={payload?.tools} />}
              {message.role === "assistant" ? (
                message.error ? (
                  <AgentErrorCard content={message.content} error={message.error} />
                ) : (
                  <Streamdown controls={{ table: false }}>{message.content}</Streamdown>
                )
              ) : (
                message.content
              )}
            </div>
          );
        })}
        {running && streamText && (
          <div className="wf-agent-msg assistant">
            <ToolCalls tools={streamTools} />
            <Streamdown controls={{ table: false }}>{streamText}</Streamdown>
          </div>
        )}
        {running && !streamText && (
          <div className="wf-agent-msg assistant thinking">
            <ToolCalls tools={streamTools} />
            <span className="wf-agent-thinking-row">
              <Loader2 size={12} className="spin" /> {t("chatThinking")}
            </span>
          </div>
        )}
      </div>
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
        <textarea
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
          <Button
            size="icon-sm"
            className="wf-agent-send"
            aria-label={t("chatSend")}
            disabled={(!draft.trim() && attachments.length === 0) || running || send.isPending || !sessionId}
            onClick={submit}
          >
            <Send size={14} />
          </Button>
        </div>
      </div>
    </aside>
  );
}
