import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CircleAlert, Loader2, Plus, Send } from "lucide-react";
import { Streamdown } from "streamdown";

import { API_BASE, api, getAuthToken, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];

export function ChatWorkspace({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [streamText, setStreamText] = React.useState<string>("");
  const streamingRef = React.useRef<string | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);

  const attachStream = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      streamingRef.current = targetSessionId;
      setStreamText("");
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
              const payload = JSON.parse(line.slice(6)) as { text: string; done: boolean };
              if (streamingRef.current === targetSessionId) setStreamText(payload.text);
            } catch {
              // partial frame — ignore
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

  const sessions = useQuery({
    queryKey: ["agent-sessions", workspace.id],
    queryFn: () => api<AgentSession[]>(`/api/agent/sessions?workspace_id=${workspace.id}`),
  });
  const activeSession =
    (sessions.data ?? []).find((session) => session.id === sessionId) ?? (sessions.data ?? [])[0] ?? null;

  const messages = useQuery({
    queryKey: ["agent-messages", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => api<AgentMessage[]>(`/api/agent/sessions/${activeSession!.id}/messages`),
    refetchInterval: 1200,
    refetchIntervalInBackground: true,
  });
  const session = useQuery({
    queryKey: ["agent-session", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => api<AgentSession>(`/api/agent/sessions/${activeSession!.id}`),
    refetchInterval: 1200,
    refetchIntervalInBackground: true,
  });
  const running = session.data?.status === "running";

  const createSession = useMutation({
    mutationFn: () =>
      api<AgentSession>("/api/agent/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id }),
      }),
    onSuccess: (created) => {
      setSessionId(created.id);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
    },
  });
  const sendMessage = useMutation({
    mutationFn: (content: string) =>
      api<AgentMessage>(`/api/agent/sessions/${activeSession!.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    onSuccess: (_data, _variables) => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["agent-messages", activeSession?.id] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
      if (activeSession) void attachStream(activeSession.id);
    },
  });

  // Reconnect to an in-flight turn (e.g. after switching sessions or reload).
  React.useEffect(() => {
    if (running && activeSession && streamingRef.current !== activeSession.id) {
      void attachStream(activeSession.id);
    }
  }, [running, activeSession, attachStream]);

  React.useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages.data?.length, running]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || running || !activeSession) return;
    sendMessage.mutate(draft.trim());
  };

  return (
    <div className="chat-grid">
      <aside className="chat-sessions panel">
        <div className="panel-head">
          <h2>{t("aiTabChat")}</h2>
          <Button variant="outline" size="sm" onClick={() => createSession.mutate()} disabled={createSession.isPending}>
            <Plus size={13} /> {t("chatNewSession")}
          </Button>
        </div>
        <div className="chat-session-list">
          {(sessions.data ?? []).map((item) => (
            <button
              key={item.id}
              type="button"
              className={activeSession?.id === item.id ? "chat-session active" : "chat-session"}
              onClick={() => setSessionId(item.id)}
            >
              <strong>{item.title}</strong>
              <small>{item.adapter}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-main panel">
        {!activeSession ? (
          <EmptyState
            icon={<Bot size={22} />}
            title={t("chatEmptyTitle")}
            body={t("chatEmptyBody")}
            action={
              <Button onClick={() => createSession.mutate()}>
                <Plus size={15} /> {t("chatNewSession")}
              </Button>
            }
          />
        ) : (
          <>
            <div className="chat-thread" ref={threadRef}>
              {(messages.data ?? []).map((message) => (
                <ChatBubble key={message.id} message={message} />
              ))}
              {running && streamText && (
                <div className="chat-bubble assistant streaming">
                  <Streamdown>{streamText}</Streamdown>
                </div>
              )}
              {running && !streamText && (
                <div className="chat-bubble assistant thinking">
                  <Loader2 size={13} className="spin" /> {t("chatThinking")}
                </div>
              )}
              {(messages.data ?? []).length === 0 && !running && (
                <EmptyState icon={<Bot size={22} />} title={t("chatEmptyTitle")} body={t("chatEmptyBody")} />
              )}
            </div>
            <form className="chat-composer" onSubmit={submit}>
              <textarea
                rows={2}
                value={draft}
                placeholder={t("chatPlaceholder")}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
              />
              <Button type="submit" disabled={!draft.trim() || running || sendMessage.isPending}>
                <Send size={14} /> {t("chatSend")}
              </Button>
            </form>
          </>
        )}
      </section>
    </div>
  );
}

function ChatBubble({ message }: { message: AgentMessage }) {
  const t = useI18n();
  const [showError, setShowError] = React.useState(false);
  return (
    <div className={`chat-bubble ${message.role}`}>
      {message.role === "assistant" ? (
        <Streamdown>{message.content}</Streamdown>
      ) : (
        <div className="chat-bubble-content">{message.content}</div>
      )}
      {message.error && (
        <button type="button" className="chat-error" onClick={() => setShowError((value) => !value)}>
          <CircleAlert size={11} /> {t("chatErrorDetail")}
          {showError && <pre>{message.error}</pre>}
        </button>
      )}
    </div>
  );
}
