import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, CornerDownRight, Loader2, MessageSquarePlus, Paperclip, Pencil, Plus, Send, Sparkles, Square, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";
import { decodeByteFallback } from "../../lib/byteFallback";

import { API_BASE, api, getAuthToken, importAsset, type Asset, type Project, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { ModelPicker } from "@/features/ai-studio/ModelPicker";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { AgentErrorCard, ToolCalls, type ToolCall } from "@/components/agent/ToolCalls";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];
type PromptSkill = components["schemas"]["PromptSkillOut"];

export function ChatWorkspace({
  workspace,
  switcher,
}: {
  workspace: Workspace;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [renamingSession, setRenamingSession] = React.useState<AgentSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<AgentSession | null>(null);
  const [attachments, setAttachments] = React.useState<Asset[]>([]);
  const [skillsOpen, setSkillsOpen] = React.useState(false);
  const skills = useQuery({
    queryKey: ["prompt-skills"],
    queryFn: () => api<PromptSkill[]>("/api/agent/prompt-skills"),
    staleTime: 60_000,
  });
  const uploadAttachment = useMutation({
    mutationFn: (file: File) =>
      importAsset({ workspaceId: workspace.id, file }),
    onSuccess: (asset) => {
      setAttachments((current) => [...current, asset]);
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const [streamText, setStreamText] = React.useState<string>("");
  const [streamTools, setStreamTools] = React.useState<ToolCall[]>([]);
  const streamingRef = React.useRef<string | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);

  // Aborts whatever stream is open. The reader used to run `for(;;) await reader.read()` with
  // no way to stop it: unmounting the view or switching session left it reading forever, each
  // leak pinning an HTTP/1.1 connection. Past the browser's ~6-per-host cap, EVERY other
  // request in the app queues behind them and the whole UI appears to freeze.
  const abortRef = React.useRef<AbortController | null>(null);

  const attachStream = React.useCallback(
    async (targetSessionId: string) => {
      if (streamingRef.current === targetSessionId) return;
      abortRef.current?.abort(); // switching sessions must close the previous stream
      const controller = new AbortController();
      abortRef.current = controller;
      streamingRef.current = targetSessionId;
      setStreamText("");
      setStreamTools([]);
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
              const payload = JSON.parse(line.slice(6)) as { text: string; done: boolean; tools?: ToolCall[] };
              if (streamingRef.current === targetSessionId) {
                setStreamText(payload.text);
                setStreamTools(payload.tools ?? []);
              }
            } catch {
              // partial frame — ignore
            }
          }
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        // An aborted stream was replaced or unmounted — the successor owns the state now, and
        // invalidating on the way out would refetch for a view that may be gone.
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
    refetchOnWindowFocus: true,
  });
  const session = useQuery({
    queryKey: ["agent-session", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => api<AgentSession>(`/api/agent/sessions/${activeSession!.id}`),
    refetchInterval: 1200,
    refetchOnWindowFocus: true,
  });
  const running = session.data?.status === "running";
  // What is still waiting behind the current answer. Read from the server rather than counted
  // locally so it survives a reload and stays right when a turn ends mid-flight.
  const queue = useQuery({
    queryKey: ["agent-queue", activeSession?.id],
    enabled: Boolean(activeSession) && running,
    queryFn: () => api<AgentMessage[]>(`/api/agent/sessions/${activeSession!.id}/queue`),
    refetchInterval: 1500,
  });
  const queuedIds = new Set((running ? queue.data ?? [] : []).map((message) => message.id));
  const refreshQueue = () => {
    void qc.invalidateQueries({ queryKey: ["agent-queue", activeSession?.id] });
    void qc.invalidateQueries({ queryKey: ["agent-messages", activeSession?.id] });
  };
  const cancelQueued = useMutation({
    mutationFn: (messageId: string) =>
      api(`/api/agent/sessions/${activeSession?.id}/queue/${messageId}`, { method: "DELETE" }),
    onSuccess: refreshQueue,
  });
  const steerQueued = useMutation({
    mutationFn: (messageId: string) =>
      api<{ steered: boolean }>(`/api/agent/sessions/${activeSession?.id}/queue/${messageId}/steer`, {
        method: "POST",
      }),
    onSuccess: (result) => {
      // A turn that ended first leaves the message queued; it will run on its own, and saying
      // "steered" would be a lie about what the agent is doing.
      if (!result.steered) toast.message(t("chatSteerTooLate"));
      refreshQueue();
    },
  });
  const showStop = running && !draft.trim() && attachments.length === 0;
  const stopTurn = useMutation({
    mutationFn: () => api<{ stopped: boolean }>(`/api/agent/sessions/${activeSession?.id}/stop`, { method: "POST" }),
    // Nothing to report either way: a successful stop is visible as the turn ending, and
    // stopping a turn that just finished is a race the user cannot see.
    meta: { silentError: true },
  });

  // 运行中的实时耗时:running 置真时记起点,每秒走字。
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
  }, [running, activeSession?.id]);

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
  // 发送时没有会话就先建一个(生成页同款「输入框直达」交互)。
  const sendMessage = useMutation({
    mutationFn: async (content: string) => {
      let targetId = activeSession?.id;
      if (!targetId) {
        const created = await api<AgentSession>("/api/agent/sessions", {
          method: "POST",
          body: JSON.stringify({ workspace_id: workspace.id }),
        });
        targetId = created.id;
        setSessionId(created.id);
      }
      const message = await api<AgentMessage>(`/api/agent/sessions/${targetId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      return { message, targetId };
    },
    onSuccess: ({ targetId }, _content, _ctx) => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
      void attachStream(targetId);
    },
  });

  const renameSession = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api<AgentSession>(`/api/agent/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ title: name }) }),
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

  // Close the stream on unmount. Views are conditionally mounted, so this is routine, not rare.
  React.useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      streamingRef.current = null;
    };
  }, []);

  // 贴底跟随:初次加载与流式输出都钉在底部;用户往上翻阅历史时不打断,
  // 翻回底部附近后恢复跟随。用 MutationObserver 是因为 markdown 渲染是
  // 异步长高的,一次性 scrollTo 会落在半截。
  React.useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    let stick = true;
    const onScroll = () => {
      stick = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    const observer = new MutationObserver(() => {
      if (stick) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    el.scrollTop = el.scrollHeight;
    return () => {
      el.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, [activeSession?.id]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    // `running` is deliberately NOT a guard any more: a message typed while the agent works
    // is a correction, and the backend injects it into the running turn (pi steering queue).
    if ((!draft.trim() && attachments.length === 0) || sendMessage.isPending) return;
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
          {/* 模式切换只保留输入框里的那一个;列表头恒定为标题,不再挤一个 seg。 */}
          <h2>{t("chatSessionsTitle")}</h2>
          <Button variant="outline" size="sm" onClick={() => createSession.mutate()} disabled={createSession.isPending}>
            <Plus size={13} /> {t("chatNewSession")}
          </Button>
        </div>
        <div className="chat-session-list">
          {sessions.isSuccess && (sessions.data ?? []).length === 0 && (
            <div className="chat-session-empty">
              <MessageSquarePlus size={16} />
              <span>{t("chatNoSessions")}</span>
            </div>
          )}
          {(sessions.data ?? []).map((item) => (
            <ContextMenu key={item.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className={activeSession?.id === item.id ? "chat-session active" : "chat-session"}
                  onClick={() => setSessionId(item.id)}
                >
                  <strong>{item.title}</strong>
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
        {/* 生成页同款:没有会话也常驻输入框,空状态居中在消息区,首次发送自动建会话。 */}
        {
          <>
            <div className="chat-thread" ref={threadRef}>
              {(messages.data ?? [])
                .filter((message) => !queuedIds.has(message.id))
                .map((message) => (
                  <ChatBubble key={message.id} message={message} />
                ))}
              {running && streamText && (
                <div className="chat-bubble assistant streaming">
                  <ToolCalls tools={streamTools} />
                  <Streamdown controls={{ table: false }}>{decodeByteFallback(streamText)}</Streamdown>
                  <div className="chat-msg-meta live">
                    <Loader2 size={11} className="spin" />
                    <span className="chat-msg-duration timecode">{elapsedSeconds}s</span>
                  </div>
                </div>
              )}
              {running && !streamText && (
                <div className="chat-bubble assistant thinking">
                  <ToolCalls tools={streamTools} />
                  <span className="chat-thinking-row">
                    <Loader2 size={13} className="spin" /> {t("chatThinking")}
                    <span className="chat-msg-duration timecode">{elapsedSeconds}s</span>
                  </span>
                </div>
              )}
              {(messages.data ?? []).length === 0 && !running && (
                <EmptyState icon={<Bot size={22} />} title={t("chatEmptyTitle")} body={t("chatEmptyBody")} />
              )}
              {sessionId && <InlineConfirmations workspaceId={workspace.id} allowKey={sessionId} />}
            </div>
            {/* Pending strip, above the composer: these have not been sent yet, so they do not
                belong in the transcript. Each one can be steered into the running turn or
                dropped — the Codex arrangement. */}
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
              <textarea
                rows={2}
                value={draft}
                placeholder={t("chatPlaceholder")}
                onChange={(event) => {
                  setDraft(event.target.value);
                  event.target.style.height = "auto";
                  event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
              />
              <div className="chat-composer-bar">
                <div className="chat-composer-left">
                  {switcher}
                  <Popover open={skillsOpen} onOpenChange={setSkillsOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant={skillsOpen ? "secondary" : "ghost"}
                        size="icon-sm"
                        aria-label={t("skillsTitle")}
                      >
                        <Sparkles size={14} />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="composer-skills" align="start" aria-label={t("skillsTitle")}>
                      <strong>{t("skillsTitle")}</strong>
                      {(skills.data ?? []).map((skill) => (
                        <button
                          key={skill.id}
                          type="button"
                          className="composer-skill"
                          onClick={() => {
                            setDraft((current) =>
                              current.trim()
                                ? current
                                : t("skillUsePrefix").replace("{name}", skill.name) + " ",
                            );
                            setSkillsOpen(false);
                          }}
                        >
                          <em>{skill.name}</em>
                          <span>{skill.description}</span>
                        </button>
                      ))}
                      {(skills.data ?? []).length === 0 && (
                        <span className="composer-skill-empty">{t("skillsEmpty")}</span>
                      )}
                    </PopoverContent>
                  </Popover>
                  <Button asChild variant="ghost" size="icon-sm" aria-label={t("attachFile")} disabled={uploadAttachment.isPending}>
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
                  <ModelPicker workspaceId={workspace.id} session={session.data ?? null} />
                </div>
                {/* One button that changes meaning, the way ChatGPT does it: while the agent
                    works it stops the turn, and the moment you type something it becomes send
                    again — because then the obvious intent is to say that, not to stop. */}
                {showStop ? (
                  <Button
                    type="button"
                    size="icon"
                    className="chat-send chat-stop"
                    aria-label={t("chatStop")}
                    onClick={() => stopTurn.mutate()}
                  >
                    <Square size={13} fill="currentColor" />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    size="icon"
                    className="chat-send"
                    aria-label={running ? t("chatSteer") : t("chatSend")}
                    disabled={(!draft.trim() && attachments.length === 0) || sendMessage.isPending}
                  >
                    <Send size={15} />
                  </Button>
                )}
              </div>
            </form>
          </>
        }
      </section>
    </div>
  );
}

function ChatBubble({ message }: { message: AgentMessage }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const payload = message.payload as { duration_seconds?: number; tools?: ToolCall[] } | null;
  const duration = payload?.duration_seconds;

  const copy = () => {
    void navigator.clipboard.writeText(message.content).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className={`chat-bubble ${message.role}`}>
      {message.role === "assistant" && <ToolCalls tools={payload?.tools} />}
      {message.role === "assistant" ? (
        message.error ? (
          <AgentErrorCard content={message.content} error={message.error} />
        ) : (
          <Streamdown controls={{ table: false }}>{decodeByteFallback(message.content)}</Streamdown>
        )
      ) : (
        <div className="chat-bubble-content">{message.content}</div>
      )}
      {/* 脚注只给助手回答:用户消息没有复制/耗时,免得药丸下方留一条空的悬停占位。 */}
      {message.role === "assistant" && (
        <div className="chat-msg-meta">
          <button type="button" className="chat-msg-copy" title={t("copyMessage")} onClick={copy}>
            {copied ? <Check size={11} /> : <Copy size={11} />}
            {copied ? t("copied") : t("copyMessage")}
          </button>
          {typeof duration === "number" && (
            <span className="chat-msg-duration timecode">{duration.toFixed(1)}s</span>
          )}
        </div>
      )}
    </div>
  );
}
