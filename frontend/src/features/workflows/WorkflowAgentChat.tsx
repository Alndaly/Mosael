import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, GripHorizontal, Loader2, Send, X } from "lucide-react";
import { Streamdown } from "streamdown";

import { API_BASE, api, getAuthToken, workflowAgentSession } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";

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
    refetchIntervalInBackground: true,
  });
  const live = useQuery({
    queryKey: ["agent-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => api<AgentSession>(`/api/agent/sessions/${sessionId}`),
    refetchInterval: 1500,
    refetchIntervalInBackground: true,
  });
  const running = live.data?.status === "running";

  const attachStream = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      streamingRef.current = targetSessionId;
      try {
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/agent/sessions/${targetSessionId}/stream`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
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
              const payload = JSON.parse(line.slice(6)) as { text: string };
              if (streamingRef.current === targetSessionId) setStreamText(payload.text);
            } catch {
              // partial frame
            }
          }
        }
      } finally {
        if (streamingRef.current === targetSessionId) {
          streamingRef.current = null;
          setStreamText("");
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

  React.useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.data?.length, streamText]);

  const send = useMutation({
    mutationFn: async (content: string) => {
      // 首条消息带上工作流上下文,智能体后续靠会话记忆 + MCP 工具工作。
      const isFirst = (messages.data ?? []).length === 0;
      const finalContent = isFirst
        ? `${t("wfAgentContext").replace("{id}", workflowId).replace("{name}", workflowName)}\n\n${content}`
        : content;
      return api<AgentMessage>(`/api/agent/sessions/${sessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: finalContent }),
      });
    },
    onSuccess: () => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
      if (sessionId) void attachStream(sessionId);
    },
  });

  const submit = () => {
    if (!draft.trim() || !sessionId || running || send.isPending) return;
    send.mutate(draft.trim());
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
        {(messages.data ?? []).map((message) => (
          <div key={message.id} className={`wf-agent-msg ${message.role}`}>
            {message.role === "assistant" ? (
              <Streamdown controls={{ table: false }}>{message.content}</Streamdown>
            ) : (
              message.content
            )}
          </div>
        ))}
        {running && streamText && (
          <div className="wf-agent-msg assistant">
            <Streamdown controls={{ table: false }}>{streamText}</Streamdown>
          </div>
        )}
        {running && !streamText && (
          <div className="wf-agent-msg assistant thinking">
            <Loader2 size={12} className="spin" /> {t("chatThinking")}
          </div>
        )}
      </div>
      <div className="wf-agent-composer">
        <textarea
          rows={2}
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
        <Button
          size="icon-sm"
          aria-label={t("chatSend")}
          disabled={!draft.trim() || running || send.isPending || !sessionId}
          onClick={submit}
        >
          <Send size={13} />
        </Button>
      </div>
    </aside>
  );
}
