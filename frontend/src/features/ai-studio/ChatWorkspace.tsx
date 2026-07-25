import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  CircleDot,
  Copy,
  CornerDownRight,
  Database,
  FileText,
  Loader2,
  MessageSquarePlus,
  Paperclip,
  Pencil,
  Plus,
  Send,
  Sparkles,
  Square,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { API_BASE, api, assetFileUrl, getAuthToken, importAsset, type Asset, type Project, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { useImagePreview } from "@/components/app/image-preview";
import { EmptyState } from "@/components/layout/EmptyState";
import { ModelPicker } from "@/features/ai-studio/ModelPicker";
import { AnalysisModePicker } from "@/features/ai-studio/AnalysisModePicker";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem } from "@/components/agent/ToolCalls";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentManifest = components["schemas"]["AgentManifestOut"];
type AgentTool = components["schemas"]["ToolSpec"];
type PromptSkill = components["schemas"]["PromptSkillOut"];
type AgentUsageEvent = {
  id: string;
  agent_message_id: string | null;
  provider: string;
  model: string;
  capability: string;
  operation: string;
  status: string;
  duration_seconds: number | null;
  units: Record<string, unknown>;
  cost_micros: number | null;
  currency: string;
  cost_confidence: string;
};

export function ChatWorkspace({
  workspace,
  switcher,
}: {
  workspace: Workspace;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const sessionKey = agentSessionSelectionKey(workspace.id);
  const [sessionId, setSessionId] = React.useState<string | null>(() => window.localStorage.getItem(sessionKey));
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
  const manifest = useQuery({
    queryKey: ["agent-manifest"],
    queryFn: () => api<AgentManifest>("/api/agent/manifest"),
    staleTime: 60_000,
  });
  const tools = useQuery({
    queryKey: ["agent-tools"],
    queryFn: () => api<AgentTool[]>("/api/agent/tools"),
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
  const [streamTimeline, setStreamTimeline] = React.useState<AgentTimelineItem[]>([]);
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
                done: boolean;
                timeline?: AgentTimelineItem[];
              };
              if (streamingRef.current === targetSessionId) {
                setStreamText(payload.text);
                setStreamTimeline(payload.timeline ?? []);
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
          // 临时流式气泡的显示条件是 running(来自 agent-session 状态)&& streamText。要消除「回答
          // 完成那一刻整页闪烁」,得让 running 转 false(气泡消失)与正式消息出现落在同一帧:一起
          // await messages + session 的 refetch,两者同时 settle → React 批处理同帧重渲染,正式气泡
          // 就位的同刻临时气泡消失,无空白也无重复。之后再清 streamText 只是收尾(气泡已因 running 消失)。
          await Promise.all([
            qc.invalidateQueries({ queryKey: ["agent-messages", targetSessionId] }),
            qc.invalidateQueries({ queryKey: ["agent-session", targetSessionId] }),
          ]);
          setStreamText("");
          setStreamTimeline([]);
          void qc.invalidateQueries({ queryKey: ["agent-usage-events", targetSessionId] });
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
  const usageEvents = useQuery({
    queryKey: ["agent-usage-events", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => api<AgentUsageEvent[]>(`/api/agent/sessions/${activeSession!.id}/usage-events`),
    refetchInterval: running ? 1200 : false,
    refetchOnWindowFocus: true,
  });
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
      window.localStorage.setItem(sessionKey, created.id);
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
        window.localStorage.setItem(sessionKey, created.id);
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
      if (sessionId === id) {
        setSessionId(null);
        window.localStorage.removeItem(sessionKey);
      }
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

  const visibleMessages = (messages.data ?? []).filter((message) => !queuedIds.has(message.id));
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

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_300px] grid-rows-[minmax(0,1fr)] gap-2 max-[1180px]:grid-cols-[220px_minmax(0,1fr)] max-[820px]:grid-cols-[minmax(0,1fr)] max-[760px]:grid-rows-[minmax(0,1fr)_auto]">
      <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[820px]:hidden">
        <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
          {/* 模式切换只保留输入框里的那一个;列表头恒定为标题,不再挤一个 seg。 */}
          <h2>{t("chatSessionsTitle")}</h2>
          <Button variant="outline" size="icon" className="h-7 w-7" title={t("chatNewSession")} aria-label={t("chatNewSession")} onClick={() => createSession.mutate()} disabled={createSession.isPending}>
            <Plus size={14} />
          </Button>
        </div>
        <div
          className={cn(
            "grid content-start gap-1 overflow-auto p-1.5 [scrollbar-gutter:stable] [scrollbar-width:none] hover:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] hover:[scrollbar-width:thin] focus-within:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] focus-within:[scrollbar-width:thin] [&::-webkit-scrollbar]:h-0 [&::-webkit-scrollbar]:w-0 hover:[&::-webkit-scrollbar]:h-1.5 hover:[&::-webkit-scrollbar]:w-1.5 focus-within:[&::-webkit-scrollbar]:h-1.5 focus-within:[&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
            sessions.isSuccess && (sessions.data ?? []).length === 0 && "content-center justify-items-center",
          )}
        >
          {sessions.isSuccess && (sessions.data ?? []).length === 0 && (
            <div className="grid justify-items-center gap-1.5 p-2.5 text-center text-xs text-muted-foreground">
              <MessageSquarePlus size={16} className="text-primary opacity-70" />
              <span>{t("chatNoSessions")}</span>
            </div>
          )}
          {(sessions.data ?? []).map((item) => (
            <ContextMenu key={item.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    "grid w-full cursor-pointer gap-px rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted",
                    activeSession?.id === item.id && "bg-accent shadow-[inset_2px_0_0_var(--primary)] hover:bg-accent",
                  )}
                  onClick={() => {
                    setSessionId(item.id);
                    window.localStorage.setItem(sessionKey, item.id);
                  }}
                >
                  <strong className="truncate text-xs font-semibold">{item.title}</strong>
                </button>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => setRenamingSession(item)}>
                  <Pencil /> {t("rename")}
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeletingSession(item)}>
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

      <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[minmax(0,1fr)_auto]">
        {/* 生成页同款:没有会话也常驻输入框,空状态居中在消息区,首次发送自动建会话。 */}
        {
          <>
            <div className="flex flex-col gap-3.5 overflow-y-auto px-4 pb-2.5 pt-7" ref={threadRef}>
              {visibleMessages.map((message) => (
                <ChatBubble key={message.id} message={message} usageEvents={usageByMessage.get(message.id) ?? []} />
              ))}
              {running && streamText && (
                <div className="relative mx-auto w-full max-w-[780px] shrink-0 text-[13.5px] leading-[1.65] [word-break:break-word]">
                  <AgentTurnContent timeline={streamTimeline} />
                  <div className="mt-1.5 flex min-h-[18px] items-center gap-1.5 text-muted-foreground">
                    <Loader2 size={11} className="animate-mibu-spin" />
                    <span className="timecode text-[11px] text-muted-foreground">
                      {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
                    </span>
                  </div>
                </div>
              )}
              {running && !streamText && (
                <div className="relative mx-auto flex w-full max-w-[780px] shrink-0 flex-col items-stretch gap-[7px] text-[13.5px] leading-[1.65] text-muted-foreground [word-break:break-word]">
                  <AgentTurnContent timeline={streamTimeline} />
                  <span className="inline-flex items-center gap-1.5 self-start whitespace-nowrap">
                    <Loader2 size={13} className="animate-mibu-spin" /> {t("chatThinking")}
                    <span className="timecode ml-0.5 text-[11px] text-muted-foreground">
                      {t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
                    </span>
                  </span>
                </div>
              )}
              {(messages.data ?? []).length === 0 && !running && (
                <div className="m-auto w-full max-w-[780px]">
                  <EmptyState icon={<Bot size={22} />} title={t("chatEmptyTitle")} body={t("chatEmptyBody")} />
                </div>
              )}
              {sessionId && <InlineConfirmations workspaceId={workspace.id} allowKey={sessionId} />}
            </div>
            {/* Pending strip, above the composer: these have not been sent yet, so they do not
                belong in the transcript. Each one can be steered into the running turn or
                dropped — the Codex arrangement. */}
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
            <form
              className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] flex-col gap-1 rounded-[22px] border border-input bg-panel pb-1.5 pl-3 pr-2.5 pt-2.5 shadow-[var(--shadow-raised)] transition-[border-color,box-shadow] duration-100 focus-within:border-ring focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_35%,transparent)]"
              onSubmit={submit}
            >
              {/* 附件条属于输入框内部(文本框上方),而不是飘在圆角框外的左上角。 */}
              {attachments.length > 0 && (
                <div className="flex flex-wrap gap-1.5 px-0.5 pb-1">
                  {attachments.map((asset) => (
                    <span
                      className="inline-flex max-w-[240px] items-center gap-[5px] rounded-full border border-border bg-panel-subtle py-[3px] pl-2 pr-1.5 text-[11px]"
                      key={asset.id}
                    >
                      <Paperclip size={10} className="shrink-0 text-muted-foreground" />
                      <span className="truncate" title={asset.name}>{asset.name}</span>
                      <button
                        type="button"
                        className="grid shrink-0 cursor-pointer place-items-center rounded-full border-0 bg-transparent p-0 text-muted-foreground hover:text-destructive"
                        onClick={() => setAttachments((current) => current.filter((item) => item.id !== asset.id))}
                        aria-label={t("delete")}
                      >
                        <X size={11} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <Textarea
                rows={2}
                className="max-h-[220px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0.5 pb-1.5 pt-0.5 text-[13.5px] leading-[1.55] shadow-none outline-none placeholder:text-muted-foreground placeholder:opacity-100 focus-visible:ring-0"
                value={draft}
                placeholder={t("chatPlaceholder")}
                onChange={(event) => {
                  setDraft(event.target.value);
                  event.target.style.height = "auto";
                  event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
              />
              <div className="flex items-center justify-between gap-1.5 pt-0.5">
                <div className="flex items-center gap-1.5">
                  {switcher}
                  <Popover open={skillsOpen} onOpenChange={setSkillsOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant={skillsOpen ? "secondary" : "ghost"}
                        size="icon"
                        aria-label={t("skillsTitle")}
                      >
                        <Sparkles size={14} />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="grid w-[300px] gap-0.5 p-2" align="start" aria-label={t("skillsTitle")}>
                      <strong className="px-1.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                        {t("skillsTitle")}
                      </strong>
                      {(skills.data ?? []).map((skill) => (
                        <button
                          key={skill.id}
                          type="button"
                          className="grid cursor-pointer gap-px rounded-md border-0 bg-transparent p-1.5 text-left transition-colors duration-100 hover:bg-secondary"
                          onClick={() => {
                            setDraft((current) =>
                              current.trim()
                                ? current
                                : t("skillUsePrefix").replace("{name}", skill.name) + " ",
                            );
                            setSkillsOpen(false);
                          }}
                        >
                          <em className="text-[12.5px] font-semibold not-italic">{skill.name}</em>
                          <span className="text-[11.5px] leading-[1.45] text-muted-foreground">{skill.description}</span>
                        </button>
                      ))}
                      {(skills.data ?? []).length === 0 && (
                        <span className="px-1.5 py-1 text-xs text-muted-foreground">{t("skillsEmpty")}</span>
                      )}
                    </PopoverContent>
                  </Popover>
                  <Button asChild variant="ghost" size="icon" aria-label={t("attachFile")} disabled={uploadAttachment.isPending}>
                    <label>
                      <input
                        type="file"
                        accept="video/*,audio/*,image/*"
                        className="hidden"
                        onChange={(event) => {
                          const file = event.currentTarget.files?.[0];
                          if (file) uploadAttachment.mutate(file);
                          event.currentTarget.value = "";
                        }}
                      />
                      {uploadAttachment.isPending ? <Loader2 size={14} className="animate-mibu-spin" /> : <Paperclip size={14} />}
                    </label>
                  </Button>
                  <ModelPicker workspaceId={workspace.id} session={session.data ?? null} />
                  <AnalysisModePicker session={session.data ?? null} />
                </div>
                {/* One button that changes meaning, the way ChatGPT does it: while the agent
                    works it stops the turn, and the moment you type something it becomes send
                    again — because then the obvious intent is to say that, not to stop. */}
                {showStop ? (
                  <Button
                    type="button"
                    size="icon"
                    className="shrink-0 rounded-full"
                    aria-label={t("chatStop")}
                    onClick={() => stopTurn.mutate()}
                  >
                    <Square size={13} fill="currentColor" />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    size="icon"
                    className="shrink-0 rounded-full"
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

      <ChatInspector
        workspace={workspace}
        session={session.data ?? activeSession}
        messages={visibleMessages}
        queue={queue.data ?? []}
        running={running}
        elapsedSeconds={elapsedSeconds}
        streamTimeline={streamTimeline}
        skills={skills.data ?? []}
        manifest={manifest.data ?? null}
        tools={tools.data ?? []}
      />
    </div>
  );
}

function ChatInspector({
  workspace,
  session,
  messages,
  queue,
  running,
  elapsedSeconds,
  streamTimeline,
  skills,
  manifest,
  tools,
}: {
  workspace: Workspace;
  session: AgentSession | null;
  messages: AgentMessage[];
  queue: AgentMessage[];
  running: boolean;
  elapsedSeconds: number;
  streamTimeline: AgentTimelineItem[];
  skills: PromptSkill[];
  manifest: AgentManifest | null;
  tools: AgentTool[];
}) {
  const t = useI18n();
  // 会话没显式设模型时,后端按供应商默认回退——与底部模型选择器同源,取生效模型而不是裸 session.model
  // (否则这里显示 —,底部却显示 deepseek-v4-pro,对不上)。
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<components["schemas"]["ProviderDefaultOut"][]>("/api/settings/provider-defaults"),
    staleTime: 60_000,
  });
  const defaultChatModel = (defaults.data ?? []).find((item) => item.capability === "chat")?.model ?? "";
  const effectiveModel = session?.model || defaultChatModel;
  const recentTools = React.useMemo(
    () => collectRecentToolCalls(messages, running ? streamTimeline : []).slice(0, 6),
    [messages, running, streamTimeline],
  );
  const userCount = messages.filter((message) => message.role === "user").length;
  const assistantCount = messages.filter((message) => message.role === "assistant").length;
  const failedCount = messages.filter((message) => message.error).length;
  const status = session?.status ?? (running ? "running" : "idle");
  const statusLabel = running
    ? `${t("agentStatusRunning")} · ${elapsedSeconds}s`
    : status === "idle"
      ? t("agentStatusIdle")
      : status;

  return (
    <aside
      className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] flex min-w-0 flex-col gap-2.5 overflow-y-auto px-2.5 pb-3 max-[1180px]:col-span-full max-[1180px]:grid max-[1180px]:max-h-60 max-[1180px]:grid-cols-2 max-[1180px]:content-start max-[820px]:grid-cols-1"
      aria-label={t("agentInspectorTitle")}
    >
      <div className="-mx-2.5 flex items-center justify-between gap-2 border-b border-border p-2.5 max-[1180px]:col-span-full">
        <h2 className="m-0 text-xs font-bold">{t("agentInspectorTitle")}</h2>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-[5px] rounded-full border border-border bg-panel-subtle px-2 py-0.5 text-[11px] font-semibold text-muted-foreground",
            running && "border-[color-mix(in_srgb,var(--primary)_42%,var(--border))] text-primary",
          )}
        >
          <CircleDot size={10} /> {statusLabel}
        </span>
      </div>

      <section className="grid gap-2 rounded-lg border border-border bg-panel-subtle p-2.5">
        <h3 className="m-0 flex items-center gap-1.5 text-[11.5px] font-bold text-muted-foreground">
          <Database size={13} /> {t("agentInspectorContext")}
        </h3>
        <dl className="m-0 grid gap-[7px]">
          <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <dt className="truncate text-[11px] text-muted-foreground">{t("agentWorkspace")}</dt>
            <dd className="m-0 truncate text-[11.5px] font-[650] text-foreground" title={workspace.name}>{workspace.name}</dd>
          </div>
          <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <dt className="truncate text-[11px] text-muted-foreground">{t("agentSession")}</dt>
            <dd className="m-0 truncate text-[11.5px] font-[650] text-foreground" title={session?.title ?? ""}>{session?.title ?? t("agentNoActiveSession")}</dd>
          </div>
          <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <dt className="truncate text-[11px] text-muted-foreground">{t("agentModel")}</dt>
            <dd className="m-0 truncate text-[11.5px] font-[650] text-foreground" title={effectiveModel}>{effectiveModel || "—"}</dd>
          </div>
          {session?.adapter && (
            <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
              <dt className="truncate text-[11px] text-muted-foreground">{t("agentFramework")}</dt>
              <dd className="m-0 truncate text-[11.5px] font-[650] text-foreground" title={session.adapter}>{session.adapter}</dd>
            </div>
          )}
          <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <dt className="truncate text-[11px] text-muted-foreground">{t("agentUpdatedAt")}</dt>
            <dd className="m-0 truncate text-[11.5px] font-[650] text-foreground">{session ? formatInspectorTime(session.updated_at) : "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="grid gap-2 rounded-lg border border-border bg-panel-subtle p-2.5">
        <h3 className="m-0 flex items-center gap-1.5 text-[11.5px] font-bold text-muted-foreground">
          <FileText size={13} /> {t("agentInspectorThread")}
        </h3>
        <div className="grid grid-cols-2 gap-1.5">
          <span className="grid gap-0.5 rounded-lg border border-border bg-panel px-2 py-[7px] text-[10.5px] text-muted-foreground">
            <strong className="text-[15px] leading-none text-foreground">{messages.length}</strong>
            {t("agentMetricMessages")}
          </span>
          <span className="grid gap-0.5 rounded-lg border border-border bg-panel px-2 py-[7px] text-[10.5px] text-muted-foreground">
            <strong className="text-[15px] leading-none text-foreground">{userCount}</strong>
            {t("agentMetricUser")}
          </span>
          <span className="grid gap-0.5 rounded-lg border border-border bg-panel px-2 py-[7px] text-[10.5px] text-muted-foreground">
            <strong className="text-[15px] leading-none text-foreground">{assistantCount}</strong>
            {t("agentMetricAssistant")}
          </span>
          <span className="grid gap-0.5 rounded-lg border border-border bg-panel px-2 py-[7px] text-[10.5px] text-muted-foreground">
            <strong className="text-[15px] leading-none text-foreground">{queue.length}</strong>
            {t("agentMetricQueue")}
          </span>
        </div>
        {failedCount > 0 && (
          <p className="m-0 text-[11.5px] leading-normal text-destructive">
            {t("agentFailedTurns").replace("{n}", String(failedCount))}
          </p>
        )}
      </section>

      <section className="grid gap-2 rounded-lg border border-border bg-panel-subtle p-2.5">
        <h3 className="m-0 flex items-center gap-1.5 text-[11.5px] font-bold text-muted-foreground">
          <Wrench size={13} /> {t("agentInspectorRecentTools")}
        </h3>
        {recentTools.length > 0 ? (
          <ul className="m-0 grid list-none gap-[5px] p-0">
            {recentTools.map((tool) => (
              <li key={tool.key} className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1.5 text-[11.5px]">
                <span
                  className={cn(
                    "h-[7px] w-[7px] rounded-full bg-muted-foreground",
                    tool.status === "done" && "bg-success",
                    tool.status === "running" && "bg-primary",
                    tool.status === "error" && "bg-destructive",
                  )}
                />
                <span className="truncate" title={tool.name}>{tool.name}</span>
                <em className="text-[10.5px] not-italic text-muted-foreground">
                  {tool.status === "error" ? t("toolStatusFailed") : tool.status === "running" ? t("toolStatusRunning") : t("toolStatusDone")}
                </em>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[11.5px] leading-normal text-muted-foreground">{t("agentNoRecentTools")}</p>
        )}
      </section>

      <section className="grid gap-2 rounded-lg border border-border bg-panel-subtle p-2.5">
        <h3 className="m-0 flex items-center gap-1.5 text-[11.5px] font-bold text-muted-foreground">
          <Sparkles size={13} /> {t("agentInspectorCapabilities")}
        </h3>
        <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
          <span className="truncate text-[11px] text-muted-foreground">{t("skillsTitle")}</span>
          <strong className="m-0 truncate text-[11.5px] font-[650] text-foreground">{skills.length}</strong>
        </div>
        <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
          <span className="truncate text-[11px] text-muted-foreground">{t("agentTools")}</span>
          <strong className="m-0 truncate text-[11.5px] font-[650] text-foreground">{tools.length}</strong>
        </div>
        {manifest && (
          <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
            <span className="truncate text-[11px] text-muted-foreground">{manifest.app}</span>
            <strong className="m-0 truncate text-[11.5px] font-[650] text-foreground">{manifest.version}</strong>
          </div>
        )}
        <div className="flex flex-wrap gap-[5px]">
          {skills.slice(0, 4).map((skill) => (
            <span
              className="max-w-full truncate rounded-full border border-border bg-panel px-[7px] py-0.5 text-[10.5px] text-muted-foreground"
              key={skill.id}
              title={skill.description}
            >
              {skill.name}
            </span>
          ))}
          {tools.slice(0, Math.max(0, 6 - Math.min(skills.length, 4))).map((tool) => (
            <span
              className="max-w-full truncate rounded-full border border-border bg-panel px-[7px] py-0.5 text-[10.5px] text-muted-foreground"
              key={tool.name}
              title={tool.description}
            >
              {tool.name}
            </span>
          ))}
        </div>
      </section>
    </aside>
  );
}

function collectRecentToolCalls(messages: AgentMessage[], streamTimeline: AgentTimelineItem[]) {
  const tools: { key: string; name: string; status: "running" | "done" | "error" }[] = [];
  const pushTimeline = (timeline: AgentTimelineItem[] | undefined, scope: string) => {
    for (const item of timeline ?? []) {
      if (item.type !== "tool") continue;
      tools.push({
        key: `${scope}:${item.tool.id}`,
        name: item.tool.name,
        status: item.tool.status,
      });
    }
  };

  for (const message of messages) {
    const payload = message.payload as { timeline?: AgentTimelineItem[] } | null;
    pushTimeline(payload?.timeline, message.id);
  }
  pushTimeline(streamTimeline, "stream");
  return tools.reverse();
}

function formatInspectorTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function numberUnit(value: unknown): number | null {
  if (typeof value === "boolean") return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function quantityForUnit(units: Record<string, unknown>, unit: "token" | "input_token" | "output_token"): number {
  const aliases = {
    token: ["token", "tokens", "total_token", "total_tokens"],
    input_token: ["input_token", "input_tokens", "prompt_tokens", "input_characters"],
    output_token: ["output_token", "output_tokens", "completion_tokens", "output_characters"],
  } satisfies Record<typeof unit, string[]>;
  for (const key of aliases[unit]) {
    const value = numberUnit(units[key]);
    if (value != null) return value;
  }
  if (unit === "token") {
    const input = quantityForUnit(units, "input_token");
    const output = quantityForUnit(units, "output_token");
    return input + output;
  }
  return 0;
}

function summarizeMessageUsage(events: AgentUsageEvent[]) {
  let inputTokens = 0;
  let outputTokens = 0;
  let totalTokens = 0;
  let durationSeconds = 0;
  let hasDuration = false;
  let unknownCostEvents = 0;
  const costByCurrency = new Map<string, number>();

  for (const event of events) {
    const units = event.units ?? {};
    const input = quantityForUnit(units, "input_token");
    const output = quantityForUnit(units, "output_token");
    const total = Math.max(quantityForUnit(units, "token"), input + output);
    inputTokens += input;
    outputTokens += output;
    totalTokens += total;
    if (typeof event.duration_seconds === "number") {
      durationSeconds += event.duration_seconds;
      hasDuration = true;
    }
    if (typeof event.cost_micros === "number") {
      const currency = event.currency || "USD";
      costByCurrency.set(currency, (costByCurrency.get(currency) ?? 0) + event.cost_micros);
    } else {
      unknownCostEvents += 1;
    }
  }

  return {
    inputTokens: Math.round(inputTokens),
    outputTokens: Math.round(outputTokens),
    totalTokens: Math.round(totalTokens),
    durationSeconds: hasDuration ? durationSeconds : null,
    costByCurrency,
    unknownCostEvents,
  };
}

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value);
}

function formatCostMicros(currency: string, micros: number): string {
  const amount = micros / 1_000_000;
  const symbol = currency === "USD" ? "$" : currency === "CNY" ? "¥" : "";
  const precision = amount > 0 && amount < 0.01 ? 6 : 4;
  const value = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: amount === 0 ? 0 : 2,
    maximumFractionDigits: precision,
  }).format(amount);
  return symbol ? `${symbol}${value}` : `${value} ${currency}`;
}

function formatUsageCost(events: ReturnType<typeof summarizeMessageUsage>, t: ReturnType<typeof useI18n>): string | null {
  const known = [...events.costByCurrency.entries()].filter(([, value]) => value >= 0);
  if (known.length > 0) {
    return t("usageCost").replace(
      "{cost}",
      known.map(([currency, micros]) => formatCostMicros(currency, micros)).join(" + "),
    );
  }
  return events.unknownCostEvents > 0 ? t("usageCostUnknown") : null;
}

// 发送时附件被拼成 `[附件 asset_id=… 名称=… 类型=…]` 交给智能体识别;用户气泡里要把它从正文里拆出来,
// 渲染成缩略图/文件胶囊,而不是把这段标记原样显示。名称可含空格,所以非贪婪匹配到 “ 类型=”。
const ATTACHMENT_TOKEN = /\n?\[附件 asset_id=(\S+) 名称=(.*?) 类型=([a-z]+)\]/g;

function parseUserContent(content: string): { text: string; attachments: { assetId: string; name: string; kind: string }[] } {
  const attachments: { assetId: string; name: string; kind: string }[] = [];
  const text = content
    .replace(ATTACHMENT_TOKEN, (_match, assetId: string, name: string, kind: string) => {
      attachments.push({ assetId, name, kind });
      return "";
    })
    .trim();
  return { text, attachments };
}

function UserAttachment({ assetId, name, kind }: { assetId: string; name: string; kind: string }) {
  const { openImagePreview } = useImagePreview();
  const src = assetFileUrl(assetId);
  if (kind === "image") {
    return (
      <button
        type="button"
        title={name}
        className="block max-h-[180px] w-fit max-w-full cursor-zoom-in overflow-hidden rounded-lg border border-border bg-black p-0"
        onClick={() => openImagePreview({ src, title: name })}
      >
        <img src={src} alt={name} loading="lazy" className="block max-h-[180px] w-auto max-w-full object-contain" />
      </button>
    );
  }
  if (kind === "video") {
    return <video src={src} controls preload="metadata" className="max-h-[200px] max-w-full rounded-lg border border-border bg-black" />;
  }
  if (kind === "audio") {
    return <audio src={src} controls preload="metadata" className="w-[260px] max-w-full" />;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-[5px] rounded-lg border border-border bg-panel px-2 py-1 text-[11.5px] text-muted-foreground">
      <Paperclip size={12} className="shrink-0" />
      <span className="truncate" title={name}>{name}</span>
    </span>
  );
}

function UserMessageContent({ content }: { content: string }) {
  const { text, attachments } = React.useMemo(() => parseUserContent(content), [content]);
  if (attachments.length === 0) return <div>{content}</div>;
  return (
    <div className="grid gap-1.5">
      {text && <div className="whitespace-pre-wrap">{text}</div>}
      <div className="flex flex-wrap gap-1.5">
        {attachments.map((att) => (
          <UserAttachment key={att.assetId} assetId={att.assetId} name={att.name} kind={att.kind} />
        ))}
      </div>
    </div>
  );
}

function ChatBubble({ message, usageEvents }: { message: AgentMessage; usageEvents: AgentUsageEvent[] }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const payload = message.payload as { usage?: { duration_seconds?: number }; timeline?: AgentTimelineItem[] } | null;
  const usage = summarizeMessageUsage(usageEvents);
  const duration = payload?.usage?.duration_seconds ?? usage.durationSeconds;
  const tokenLabel =
    usage.totalTokens > 0 ? t("usageTokens").replace("{n}", formatTokenCount(usage.totalTokens)) : null;
  const tokenTitle =
    usage.inputTokens > 0 || usage.outputTokens > 0
      ? `${t("homeLegendInputTokens")} ${formatTokenCount(usage.inputTokens)} · ${t("homeLegendOutputTokens")} ${formatTokenCount(usage.outputTokens)}`
      : undefined;
  const costLabel = formatUsageCost(usage, t);

  const copy = () => {
    void navigator.clipboard.writeText(message.content).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div
      className={
        message.role === "assistant"
          ? "group/bubble relative mx-auto w-full max-w-[780px] shrink-0 text-[13.5px] leading-[1.65] [word-break:break-word]"
          : "ml-auto mr-[max(calc((100%-780px)/2),0px)] w-fit max-w-[min(560px,82%)] shrink-0 whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-[13.5px] leading-[1.65] text-foreground [word-break:break-word]"
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
      {/* 脚注只给助手回答:用户消息没有复制/耗时,免得药丸下方留一条空的悬停占位。 */}
      {message.role === "assistant" && (
        <div className="mt-1.5 flex min-h-[18px] items-center gap-1.5 opacity-0 transition-opacity duration-[120ms] group-hover/bubble:opacity-100">
          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1 rounded-sm border-0 bg-transparent px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground"
            title={t("copyMessage")}
            onClick={copy}
          >
            {copied ? <Check size={11} /> : <Copy size={11} />}
            {copied ? t("copied") : t("copyMessage")}
          </button>
          {typeof duration === "number" && (
            <span className="timecode text-[11px] text-muted-foreground">
              {t("usageDuration").replace("{t}", formatElapsedSeconds(duration))}
            </span>
          )}
          {tokenLabel && (
            <span className="text-[11px] text-muted-foreground" title={tokenTitle}>
              {tokenLabel}
            </span>
          )}
          {costLabel && <span className="text-[11px] text-muted-foreground">{costLabel}</span>}
        </div>
      )}
    </div>
  );
}
