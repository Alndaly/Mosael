import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CircleAlert, Loader2, Paperclip, Pencil, Plus, Send, Trash2, X } from "lucide-react";
import { Streamdown } from "streamdown";

import { API_BASE, api, getAuthToken, importAsset, type Asset, type Project, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];

export function ChatWorkspace({ workspace, project }: { workspace: Workspace; project?: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [renamingSession, setRenamingSession] = React.useState<AgentSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<AgentSession | null>(null);
  const [attachments, setAttachments] = React.useState<Asset[]>([]);
  const uploadAttachment = useMutation({
    mutationFn: (file: File) =>
      importAsset({ workspaceId: workspace.id, projectId: project?.id ?? "", file }),
    onSuccess: (asset) => {
      setAttachments((current) => [...current, asset]);
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
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

  const renameSession = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api<AgentSession>(`/api/agent/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
    onSuccess: () => {
      setRenamingSession(null);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
    },
  });
  const deleteSession = useMutation({
    mutationFn: (id: string) => api(`/api/agent/sessions/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      setDeletingSession(null);
      if (sessionId === id) setSessionId(null);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
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
    if ((!draft.trim() && attachments.length === 0) || running || !activeSession) return;
    let content = draft.trim();
    for (const asset of attachments) {
      content += `\n[附件 asset_id=${asset.id} 名称=${asset.name} 类型=${asset.kind}]`;
    }
    sendMessage.mutate(content.trim());
    setAttachments([]);
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
            <ContextMenu key={item.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className={activeSession?.id === item.id ? "chat-session active" : "chat-session"}
                  onClick={() => setSessionId(item.id)}
                >
                  <strong>{item.title}</strong>
                  <small>{item.adapter}</small>
                </button>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => setRenamingSession(item)}>
                  <Pencil /> {t("rename")}
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem destructive onSelect={() => setDeletingSession(item)}>
                  <Trash2 /> {t("delete")}
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenu>
          ))}
        </div>

        <RenameDialog
          open={renamingSession !== null}
          title={t("renameSession")}
          initialValue={renamingSession?.title ?? ""}
          onCancel={() => setRenamingSession(null)}
          onSubmit={(name) => renamingSession && renameSession.mutate({ id: renamingSession.id, name })}
        />
        <ConfirmDialog
          open={deletingSession !== null}
          title={t("deleteConfirmTitle")}
          body={t("deleteSessionBody")}
          onCancel={() => setDeletingSession(null)}
          onConfirm={() => deletingSession && deleteSession.mutate(deletingSession.id)}
        />
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
            {attachments.length > 0 && (
              <div className="chat-attachments">
                {attachments.map((asset) => (
                  <span className="chat-attachment" key={asset.id}>
                    {asset.name}
                    <button
                      type="button"
                      onClick={() => setAttachments((current) => current.filter((item) => item.id !== asset.id))}
                      aria-label={t("delete")}
                    >
                      <X size={11} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <form className="chat-composer" onSubmit={submit}>
              <Button asChild variant="ghost" size="icon-sm" aria-label="attach" disabled={uploadAttachment.isPending}>
                <label>
                  <input
                    type="file"
                    accept="video/*,audio/*,image/*"
                    className="hidden-input"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      if (file) uploadAttachment.mutate(file);
                      event.currentTarget.value = "";
                    }}
                  />
                  {uploadAttachment.isPending ? <Loader2 size={14} className="spin" /> : <Paperclip size={14} />}
                </label>
              </Button>
              <textarea
                rows={1}
                value={draft}
                placeholder={t("chatPlaceholder")}
                onChange={(event) => {
                  setDraft(event.target.value);
                  event.target.style.height = "auto";
                  event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
              />
              <Button
                type="submit"
                size="icon"
                className="chat-send"
                aria-label={t("chatSend")}
                disabled={(!draft.trim() && attachments.length === 0) || running || sendMessage.isPending}
              >
                <Send size={15} />
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
