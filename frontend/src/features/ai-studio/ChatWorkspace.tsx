import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, ChevronDown, ChevronRight, CircleDot, Copy, CornerDownRight, Database, Loader2, MessageSquarePlus, Paperclip, Pencil, Plus, SearchX, Send, Sparkles, Square, Trash2, Wrench, X } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, api, getAuthToken, importAsset, type Asset, type Project, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { AttachmentChips, textAttachmentBlock, useComposerAttachments } from "@/components/agent/composerAttachments";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, ModalShell, RenameDialog } from "@/components/app/modals";
import { UserMessageContent, attachmentToken } from "@/features/ai-studio/userMessage";
import { MessageUsageFooter, type AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { EmptyState } from "@/components/layout/EmptyState";
import { ModelPicker } from "@/features/ai-studio/ModelPicker";
import { SessionSettingsMenu } from "@/components/agent/SessionSettingsMenu";
import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { CompactionNotice, type CompactionInfo, type ContextInfo } from "@/components/agent/ContextMeter";
import { InspectorCard, InspectorRow } from "@/components/agent/InspectorCard";
import { PlanCard, type PlanStep } from "@/components/agent/PlanCard";
import { InlineConfirmations } from "@/components/agent/InlineConfirmations";
import { AgentErrorCard, AgentTurnContent, type AgentTimelineItem, type ToolCall } from "@/components/agent/ToolCalls";
import { formatElapsedSeconds } from "@/lib/time";
import { SessionShareMenuItem } from "@/features/ai-studio/SessionShareMenuItem";
import { AgentStatusIcon, ToolName, toAgentStatus } from "@/components/agent/StatusIcon";
import { readToolPayload } from "@/features/ai-studio/toolPayload";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentManifest = components["schemas"]["AgentManifestOut"];
type AgentTool = components["schemas"]["ToolSpec"];

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
  // 附件三种入口(选文件 / 拖放 / 粘贴)与工作流助手共用同一套逻辑,见 composerAttachments。
  const attach = useComposerAttachments(workspace.id);
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
  const showStop = running && !draft.trim() && attach.isEmpty;
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
    if ((!draft.trim() && attach.isEmpty) || sendMessage.isPending) return;
    // 文本文件内联成围栏上下文、媒体编码成附件标记 —— 与工作流助手同一种拼法,
    // 于是两边发出来的气泡也长得一样。
    const fileBlock = textAttachmentBlock(attach.files, t("chatAttached"));
    let content = draft.trim() || attach.files.map((file) => `[${t("chatAttached")} ${file.name}]`).join("\n");
    for (const asset of attach.media) content += attachmentToken(asset);
    sendMessage.mutate([content.trim(), fileBlock].filter(Boolean).join("\n\n"));
    attach.clear();
  };

  const visibleMessages = (messages.data ?? []).filter((message) => !queuedIds.has(message.id));

  /** 水位由会话详情**现算**给出,不从消息 payload 里翻。
   *  挂在消息上等于"必须先成功跑一轮才看得到" —— 而想知道"还能聊多久"的时刻恰恰在开口之前:
   *  刚打开旧会话、刚换过模型、上一轮失败了,这些时候都没有新的一轮可以带回这个数。 */
  const context = (session.data?.context ?? null) as ContextInfo | null;

  const compactContext = useMutation({
    mutationFn: () =>
      api<{ compaction: CompactionInfo | null }>(`/api/agent/sessions/${activeSession!.id}/compact`, {
        method: "POST",
      }),
    // 压成功了对话里会多一条整理记录,那本身就是反馈;**没得压和压失败必须说出来** ——
    // 此前两种情况都只是 loading 闪一下就没了,用户无从判断是没生效、还是不需要。
    onSuccess: (result) => {
      void messages.refetch();
      void qc.invalidateQueries({ queryKey: ["agent-session", activeSession?.id] });
      if (!result?.compaction) toast.message(t("agentCompactNothing"));
    },
    onError: (error) => toast.error(`${t("agentCompactFailed")}:${(error as Error).message}`),
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

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_300px] grid-rows-[minmax(0,1fr)] gap-2 max-[1180px]:grid-cols-[220px_minmax(0,1fr)] max-[820px]:grid-cols-[minmax(0,1fr)] max-[760px]:grid-rows-[minmax(0,1fr)_auto]">
      <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[820px]:hidden">
        <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-ui-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
          {/* 模式切换只保留输入框里的那一个;列表头恒定为标题,不再挤一个 seg。 */}
          <h2>{t("chatSessionsTitle")}</h2>
          <Button variant="outline" size="icon" className="h-7 w-7" title={t("chatNewSession")} aria-label={t("chatNewSession")} onClick={() => createSession.mutate()} loading={createSession.isPending}>
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
            <EmptyState size="compact" icon={<MessageSquarePlus size={15} />} title={t("chatNoSessions")} />
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
                <SessionShareMenuItem session={item} kind="agent_session" workspaceId={workspace.id} queryKey="agent-sessions" />
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
            {/* 横向和纵向一起锁:flex 子项默认 min-width:auto,一段长代码块或长 URL 会把这一列
                 撑宽,整个对话区就能左右滚。代码块自己的 overflow-x-auto 只在父容器被约束时生效。 */}
            <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-2.5 pt-7" ref={threadRef}>
              {visibleMessages.map((message) => (
                <ChatBubble key={message.id} message={message} usageEvents={usageByMessage.get(message.id) ?? []} />
              ))}
              {running && streamText && (
                <div className="relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]">
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
                <div className="relative mx-auto flex w-full max-w-[780px] shrink-0 flex-col items-stretch gap-[7px] text-ui-md leading-[1.65] text-muted-foreground [word-break:break-word]">
                  <AgentTurnContent timeline={streamTimeline} />
                  <span className="inline-flex items-center gap-1.5 self-start whitespace-nowrap">
                    <Loader2 size={13} className="animate-openstudio-spin" /> {t("chatThinking")}
                    <span className="timecode ml-0.5 text-ui-xs text-muted-foreground">
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
            <form
              className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] flex-col gap-1 rounded-[22px] border border-input bg-panel pb-1.5 pl-3 pr-2.5 pt-2.5 shadow-[var(--shadow-raised)] transition-[border-color,box-shadow] duration-100 focus-within:border-ring focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_35%,transparent)]"
              onSubmit={submit}
            >
              {/* 附件条属于输入框内部(文本框上方),而不是飘在圆角框外的左上角。 */}
              <AttachmentChips attachments={attach} className="flex flex-wrap gap-1.5 px-0.5 pb-1" />
              <Textarea
                rows={2}
                className="max-h-[220px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0.5 pb-1.5 pt-0.5 text-ui-md leading-[1.55] shadow-none outline-none placeholder:text-muted-foreground placeholder:opacity-100 focus-visible:ring-0"
                value={draft}
                placeholder={t("chatPlaceholder")}
                onChange={(event) => {
                  setDraft(event.target.value);
                  event.target.style.height = "auto";
                  event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
                }}
                onPaste={attach.onPaste}
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
                  <Button asChild variant="ghost" size="icon" aria-label={t("attachFile")} disabled={attach.uploading}>
                    <label>
                      <input
                        type="file"
                        multiple
                        className="hidden"
                        onChange={(event) => {
                          void attach.accept(event.currentTarget.files);
                          event.currentTarget.value = "";
                        }}
                      />
                      {attach.uploading ? <Loader2 size={14} className="animate-openstudio-spin" /> : <Paperclip size={14} />}
                    </label>
                  </Button>
                  <ModelPicker workspaceId={workspace.id} session={session.data ?? null} />
                  {/* 分析方式、思考档位、上下文整理收进这里 —— 它们是"配好就不再动"的东西,
                      和每次都要用的模式/附件/模型平铺在一起只会稀释后者。 */}
                  <SessionSettingsMenu
                    session={session.data ?? null}
                    context={context}
                    compacting={compactContext.isPending}
                    onCompact={running ? undefined : () => compactContext.mutate()}
                  />
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
                    loading={stopTurn.isPending}
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
                    disabled={(!draft.trim() && attach.isEmpty) || attach.uploading} loading={sendMessage.isPending}
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
  const [toolBrowser, setToolBrowser] = React.useState(false);
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
            "inline-flex shrink-0 items-center gap-[5px] rounded-full border border-border bg-panel-subtle px-2 py-0.5 text-ui-xs font-semibold text-muted-foreground",
            running && "border-[color-mix(in_srgb,var(--primary)_42%,var(--border))] text-primary",
          )}
        >
          <CircleDot size={10} /> {statusLabel}
        </span>
      </div>

      {/* 概览。此前是两块:一块五行键值(其中「当前会话」就是你正看着的这个对话、「框架 pi」是
          内部实现、「更新」永远是刚刚),另一块把四个数字铺成盒中盒的砖(消息=用户+助手,三个数
          说的是同一件事)。留下的是**看了会改变你下一步动作**的:在哪个工作区、用哪个模型、
          有没有消息在排队、有没有回合失败。 */}
      <InspectorCard icon={Database} title={t("agentInspectorOverview")}>
        <InspectorRow label={t("agentWorkspace")} value={workspace.name} title={workspace.name} />
        <InspectorRow label={t("agentModel")} value={effectiveModel || "—"} title={effectiveModel} />
        {/* 排队只在真有东西排队时出现 —— 一个常驻的 0 不构成信息。 */}
        {queue.length > 0 && <InspectorRow label={t("agentMetricQueue")} value={queue.length} />}
        {failedCount > 0 && (
          <p className="m-0 text-ui-xs leading-normal text-destructive">
            {t("agentFailedTurns").replace("{n}", String(failedCount))}
          </p>
        )}
      </InspectorCard>

      {/* 计划排在工具之前:等待时最想知道的是"它打算做什么、做到哪了",
          而不是"刚才调了哪个工具"。没有计划时整块不渲染。 */}
      <PlanCard plan={(session?.plan ?? null) as PlanStep[] | null} />

      {/* 「最近工具」与「能力」原本是两块 —— 一块只有名字和状态(看不出做了什么),另一块把
          36 个工具铺成四行胶囊(占掉半个侧栏,而那 8 个只是注册表顺序的前 8 个)。
          合成一块:头部一行交代规模与版本,主体是可展开看参数/结果的最近调用,
          全部工具收进一个带搜索的弹层——要查一个工具能干嘛时才打开。 */}
      <InspectorCard
        icon={Wrench}
        title={t("agentInspectorRecentTools")}
        aside={
          // 「看全部工具」是次要动作,所以走标题行右侧那个位 —— 和计划的 3/3 同一个位置、同一种
          // 分量。整宽 outline 按钮会和这块的主内容(最近调用)一样重,而它其实是偶尔才点的。
          <button
            type="button"
            className="flex cursor-pointer items-center gap-0.5 border-0 bg-transparent p-0 text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => setToolBrowser(true)}
          >
            <span className="tabular-nums">{t("agentToolsAll").replace("{n}", String(tools.length))}</span>
            <ChevronRight size={11} />
          </button>
        }
      >
        {recentTools.length > 0 ? (
          // gap-1 和「任务计划」同一个节奏。此前这里没有 gap、靠每行一条 border-b 分开 ——
          // **分隔线是在补缺失的间距**,而它又是整个检查器里唯一一处横线,三块并排就格格不入。
          <ul className="m-0 grid list-none gap-1 p-0">
            {recentTools.map(({ key, call }) => (
              <RecentToolRow key={key} call={call} />
            ))}
          </ul>
        ) : (
          <p className="m-0 text-ui-xs leading-normal text-muted-foreground">{t("agentNoRecentTools")}</p>
        )}
        <ToolBrowser
          open={toolBrowser}
          onOpenChange={setToolBrowser}
          tools={tools}
          version={manifest?.version ?? ""}
        />
      </InspectorCard>
    </aside>
  );
}

type RecentToolCall = { key: string; call: ToolCall };

/** 一次调用:一行状态点 + 名字 + 耗时,点开就地展开参数与结果。
 *  就地展开而不是弹层 —— 看这一栏时人在扫历史,弹层会打断这个动作。 */
function RecentToolRow({ call }: { call: ToolCall }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const seconds = call.usage?.duration_seconds;
  const hasDetail = call.args != null || call.result != null;
  return (
    <li className="grid min-w-0">
      <button
        type="button"
        className="-mx-1 grid min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-1.5 rounded border-0 bg-transparent px-1 py-1 text-left text-ui-xs text-foreground transition-colors hover:bg-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <AgentStatusIcon status={toAgentStatus(call.status)} />
        <ToolName name={call.name} />
        <em className="not-italic tabular-nums text-ui-xs text-muted-foreground">
          {call.status === "error"
            ? t("toolStatusFailed")
            : call.status === "running"
              ? t("toolStatusRunning")
              : typeof seconds === "number"
                ? `${seconds}s`
                : t("toolStatusDone")}
        </em>
        <ChevronDown size={12} className={cn("shrink-0 text-muted-foreground/70 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="grid gap-1 pb-1.5 pl-[18px]">
          {hasDetail ? (
            <>
              {call.args != null && <ToolPayload label={t("agentToolArgs")} value={call.args} />}
              {call.result != null && <ToolPayload label={t("agentToolResult")} value={call.result} />}
            </>
          ) : (
            <p className="m-0 text-ui-xs text-muted-foreground">{t("agentToolNoDetail")}</p>
          )}
        </div>
      )}
    </li>
  );
}

/** 参数/结果都可能很长(read_kb_document 能回几千字),所以限高可滚,不让它撑开整个侧栏。 */
function ToolPayload({ label, value }: { label: string; value: unknown }) {
  // 拆掉 MCP 信封再显示 —— 直接 stringify 会把里层 JSON 二次转义成满屏 \n 和 \"。
  // 见 toolPayload.ts;那一步是纯函数,有单测。
  const text = readToolPayload(value);
  return (
    <div className="grid gap-0.5">
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <pre className="m-0 max-h-28 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-panel p-1.5 font-mono text-ui-xs leading-[1.5] text-muted-foreground">
        {text}
      </pre>
    </div>
  );
}

function ToolBrowserRow({ tool }: { tool: AgentTool }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  return (
    <button
      type="button"
      className="grid min-w-0 cursor-pointer gap-0.5 border-0 border-b border-border/50 bg-transparent px-0.5 py-2 text-left last:border-b-0"
      onClick={() => setOpen((value) => !value)}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <ToolName name={tool.name} />
        {tool.confirmation && (
          <span className="shrink-0 rounded-full border border-border px-1.5 py-px text-ui-2xs font-normal text-muted-foreground">
            {t("agentToolNeedsConfirm")}
          </span>
        )}
      </span>
      <span
        className={cn(
          "min-w-0 break-words text-ui-xs leading-[1.5] text-muted-foreground",
          !open && "line-clamp-2",
        )}
      >
        {tool.description}
      </span>
    </button>
  );
}

/** 全部工具:带搜索,列名字 + 说明 + 是否走确认卡。
 *  36 个工具铺在侧栏里没人读得完,而"这个工具能干嘛"是偶发问题 —— 需要时打开就好。 */
function ToolBrowser({
  open,
  onOpenChange,
  tools,
  version,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  tools: AgentTool[];
  version?: string;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const needle = query.trim().toLowerCase();
  const matched = needle
    ? tools.filter((tool) => `${tool.name} ${tool.description}`.toLowerCase().includes(needle))
    : tools;
  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={`${t("agentInspectorCapabilities")} · ${tools.length}`}>
      <div className="grid min-w-0 gap-2">
        <Input value={query} placeholder={t("agentToolsSearch")} onChange={(event) => setQuery(event.target.value)} />
        {/* 一行一个工具、发丝线分隔,而不是一堆卡片盒子 —— 三十多条时盒子的边框比内容还抢眼。
            说明默认夹到两行(工具说明是写给模型看的,动辄一整段),点开看全文。
            **横向必须锁死**:grid 子项默认 min-width:auto,长英文单词会把整个弹窗撑宽,
            于是内容跟着左右晃。min-w-0 + break-words 是这里唯一有效的组合。 */}
        <div className="grid max-h-[52vh] min-w-0 gap-px overflow-y-auto overflow-x-hidden">
          {matched.map((tool) => (
            <ToolBrowserRow key={tool.name} tool={tool} />
          ))}
          {/* 「搜不到」和「还没有」是两回事:前者的下一步是**清掉筛选**,所以给一个能点的出口,
              而不是一句无处可去的灰字。 */}
          {matched.length === 0 && (
            <EmptyState
              size="compact"
              icon={<SearchX size={15} />}
              title={t("agentToolNoMatch")}
              body={t("agentToolNoMatchBody").replace("{q}", query)}
              action={
                <Button size="sm" variant="outline" onClick={() => setQuery("")}>
                  {t("clearSearch")}
                </Button>
              }
            />
          )}
        </div>
        {version && (
          <p className="m-0 text-right text-ui-2xs text-muted-foreground">
            {t("agentVersion")} {version}
          </p>
        )}
      </div>
    </ModalShell>
  );
}

/** 最近的工具调用。**带上参数与结果** —— 面板此前只留了名字和状态,而"它到底做了什么"
 *  恰恰是看这一栏的人想知道的,于是那一栏只能证明"有事发生过"。 */
function collectRecentToolCalls(messages: AgentMessage[], streamTimeline: AgentTimelineItem[]) {
  const tools: RecentToolCall[] = [];
  const pushTimeline = (timeline: AgentTimelineItem[] | undefined, scope: string) => {
    for (const item of timeline ?? []) {
      if (item.type !== "tool") continue;
      tools.push({ key: `${scope}:${item.tool.id}`, call: item.tool });
    }
  };

  for (const message of messages) {
    const payload = message.payload as { timeline?: AgentTimelineItem[] } | null;
    pushTimeline(payload?.timeline, message.id);
  }
  pushTimeline(streamTimeline, "stream");
  return tools.reverse();
}


function ChatBubble({ message, usageEvents }: { message: AgentMessage; usageEvents: AgentUsageEvent[] }) {
  const payload = message.payload as
    | { usage?: { duration_seconds?: number }; timeline?: AgentTimelineItem[]; compaction?: CompactionInfo }
    | null;
  // 手动压缩留下的是一条 role=system、内容为空的消息,只承载压缩标记。
  if (message.role === "system") {
    return payload?.compaction ? (
      <div className="mx-auto w-full max-w-[780px] shrink-0">
        <CompactionNotice info={payload.compaction} />
      </div>
    ) : null;
  }
  return (
    <div
      className={
        message.role === "assistant"
          ? "group/bubble relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]"
          : "ml-auto mr-[max(calc((100%-780px)/2),0px)] w-fit max-w-[min(560px,82%)] shrink-0 whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]"
      }
    >
      {/* 自动压缩发生在这一轮开始前,标记就排在这条回复之前 —— 位置本身在说"从这里往前被整理过"。 */}
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
      {/* 脚注只给助手回答:用户消息没有复制/耗时,免得药丸下方留一条空的悬停占位。 */}
      {message.role === "assistant" && (
        <MessageUsageFooter
          content={message.content}
          usageEvents={usageEvents}
          durationOverride={payload?.usage?.duration_seconds}
          className="opacity-0 transition-opacity duration-[120ms] group-hover/bubble:opacity-100"
        />
      )}
    </div>
  );
}
