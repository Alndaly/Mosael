import { useNoteAttachments } from "@/features/notes/useNoteAttachments";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import React from "react";
import { StudioIndex } from "@/components/layout/StudioIndex";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, CircleDot, Database, Loader2, PanelRight, Paperclip, SearchX, Send, Sparkles, Square, Wrench } from "lucide-react";
import { toast } from "sonner";

import {
  agentManifest,
  compactAgentSession,
  createAgentSession,
  dropQueuedMessage,
  getAgentSession,
  listAgentMessages,
  listAgentQueue,
  listAgentSessions,
  listAgentTools,
  listAgentUsageEvents,
  sendAgentMessage,
  steerQueuedMessage,
  stopAgentSession,
  type Workspace,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { useAgentTurnStream } from "@/features/agent/useAgentTurnStream";
import { textAttachmentBlock, useComposerAttachments } from "@/features/agent/composerAttachments";
import { ComposerChips } from "@/features/agent/ComposerChips";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { JSONContent } from "@tiptap/react";

import { ChatComposer, appendText, collectReferences, documentText, emptyDocument } from "@/features/agent/ChatComposer";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import type { AgentReference } from "@/features/agent/references";
import { ModalShell } from "@/components/app/modals";
import { AgentStatusRow } from "@/features/agent/AgentStatusRow";
import { ChatBubble } from "@/features/agent/ChatBubble";
import { SessionList } from "@/features/ai-studio/SessionList";
import { attachmentToken, chatMediaGallery } from "@/features/agent/userMessage";
import { type AgentUsageEvent } from "@/features/agent/messageUsage";
import { EmptyState } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { DictateButton } from "@/features/agent/DictateButton";
import { ModelPicker } from "@/features/agent/ModelPicker";
import { SessionSettingsMenu } from "@/features/agent/SessionSettingsMenu";
import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";
import { type CompactionInfo, type ContextInfo } from "@/features/agent/ContextMeter";
import { InspectorCard, InspectorRow } from "@/components/layout/InspectorCard";
import { PlanCard, planHistory, type PlanStep } from "@/features/agent/PlanCard";
import { JumpToLatest, useStickToBottom } from "@/features/agent/stickToBottom";
import { QueuedMessages } from "@/features/agent/QueuedMessages";
import { InlineConfirmations } from "@/features/agent/InlineConfirmations";
import { InlineQuestions } from "@/features/agent/InlineQuestions";
import { isRedundantAnswerRecord, recordedQuestionIds } from "@/features/agent/answerRecords";
import { AgentTurnContent, type AgentTimelineItem, type ToolCall } from "@/features/agent/ToolCalls";
import { formatElapsedSeconds } from "@/lib/time";
import { AgentStatusIcon, ToolName, toAgentStatus } from "@/features/agent/StatusIcon";
import { readToolPayload } from "@/features/ai-studio/toolPayload";
import { TraceStatsBar, TraceView } from "@/features/agent/trace/TraceView";
import { buildTurns } from "@/features/agent/trace/traceModel";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { SIDEBAR_HANDLE_CLASS, handleOffset, useSidePanels } from "@/lib/useResizableSidebar";
import { InspectorSubagentList, SubagentBreadcrumb, SubagentButton, SubagentSessionView, type SubagentRun } from "@/features/agent/SubagentPanel";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentMessage = components["schemas"]["AgentMessageOut"];
type AgentManifest = components["schemas"]["AgentManifestOut"];
type AgentTool = components["schemas"]["ToolSpec"];

//: 分栏宽度的边界。上限挡的是"把中间对话挤没了",下限挡的是"栏窄到内容全在换行"。
export const AI_PANEL_BOUNDS = {
  left: { min: 180, max: 340, fallback: 240 },
  right: { min: 240, max: 460, fallback: 300 },
} as const;

/* 输入框那一列的宽度 —— 队列条和它下面那行脚注共用这一个。
   写死三遍的结果是窗口变窄时只有输入框缩进去,队列条仍顶着两侧边缘,同一件事的几个盒子对不齐。 */
const COMPOSER_COLUMN = "mx-auto w-[min(780px,calc(100%-32px))]";

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
  //: 草稿是**编辑器文档**,不是字符串 —— `@` 出来的引用是原子节点(见 ChatComposer)。
  const [draft, setDraft] = React.useState<JSONContent>(emptyDocument);
  const draftText = React.useMemo(() => documentText(draft), [draft]);
  const noteAttach = useNoteAttachments(workspace.id);
  // 附件三种入口(选文件 / 拖放 / 粘贴)与工作流助手共用同一套逻辑,见 composerAttachments。
  const attach = useComposerAttachments(workspace.id);
  const manifest = useQuery({
    queryKey: ["agent-manifest"],
    queryFn: () => agentManifest<AgentManifest>(),
    staleTime: 60_000,
  });
  const tools = useQuery({
    queryKey: ["agent-tools"],
    queryFn: () => listAgentTools<AgentTool>(),
    staleTime: 60_000,
  });
  // 连流 → 攒状态 → 收尾失效:**只有一份**,和画布助手共用(见 useAgentTurnStream)。
  // 此前两个面板各写一遍,而收尾那一步已经分岔 —— 隔壁每答完一句都会闪一下。
  const { streamText, streamTimeline, attach: attachStream } = useAgentTurnStream();
  //「对话」读答案,「轨迹」读执行。记住选择:排查问题的人往往连着看好几个会话的轨迹。
  const [view, setView] = usePersistentTab<"chat" | "trace">("agent-view", "chat", ["chat", "trace"]);

  const sessions = useQuery({
    queryKey: ["agent-sessions", workspace.id],
    queryFn: () => listAgentSessions(workspace.id),
  });
  const activeSession =
    (sessions.data ?? []).find((session) => session.id === sessionId) ?? (sessions.data ?? [])[0] ?? null;
  //: 贴底跟随。resetKey 用会话 id:换会话该从底部重新开始。
  const stick = useStickToBottom<HTMLDivElement>(activeSession?.id);

  const messages = useQuery({
    queryKey: ["agent-messages", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => listAgentMessages(activeSession!.id),
    refetchInterval: 1200,
    refetchOnWindowFocus: true,
  });
  const session = useQuery({
    queryKey: ["agent-session", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => getAgentSession(activeSession!.id),
    refetchInterval: 1200,
    refetchOnWindowFocus: true,
  });
  const running = session.data?.status === "running";
  //: 会话清单还在路上,或者选中的这条会话的消息还在路上。两者都不算"这条会话是空的"。
  //: `enabled` 为假时 React Query 的 status 也是 pending,所以要先确认真的有一条会话在读。
  const sessionLoading = sessions.isPending || (Boolean(activeSession) && messages.isPending);
  //: 免提模式念的就是最后一条**成功**的助手回复;失败的那条由 failure 单独念(它的 content
  //: 是「智能体执行失败」这类占位,念它等于什么都没说)。
  
  
  const usageEvents = useQuery({
    queryKey: ["agent-usage-events", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => listAgentUsageEvents<AgentUsageEvent>(activeSession!.id),
    refetchInterval: running ? 1200 : false,
    refetchOnWindowFocus: true,
  });
  // What is still waiting behind the current answer. Read from the server rather than counted
  // locally so it survives a reload and stays right when a turn ends mid-flight.
  const queue = useQuery({
    queryKey: ["agent-queue", activeSession?.id],
    enabled: Boolean(activeSession) && running,
    queryFn: () => listAgentQueue(activeSession!.id),
    refetchInterval: 1500,
  });
  const queuedIds = new Set((running ? queue.data ?? [] : []).map((message) => message.id));
  const refreshQueue = () => {
    void qc.invalidateQueries({ queryKey: ["agent-queue", activeSession?.id] });
    void qc.invalidateQueries({ queryKey: ["agent-messages", activeSession?.id] });
  };
  const cancelQueued = useMutation({
    mutationFn: (messageId: string) =>
      dropQueuedMessage(String(activeSession?.id), messageId),
    onSuccess: refreshQueue,
  });
  const steerQueued = useMutation({
    mutationFn: (messageId: string) =>
      steerQueuedMessage(String(activeSession?.id), messageId),
    onSuccess: (result) => {
      // A turn that ended first leaves the message queued; it will run on its own, and saying
      // "steered" would be a lie about what the agent is doing.
      if (!result.steered) toast.message(t("chatSteerTooLate"));
      refreshQueue();
    },
  });
  const showStop = running && !draftText.trim() && attach.isEmpty && !noteAttach.hasNotes;
  const stopTurn = useMutation({
    mutationFn: () => stopAgentSession(String(activeSession?.id)),
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
      createAgentSession({ workspace_id: workspace.id }),
    onSuccess: (created) => {
      setSessionId(created.id);
      window.localStorage.setItem(sessionKey, created.id);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
    },
  });
  // 发送时没有会话就先建一个(生成页同款「输入框直达」交互)。
  const sendMessage = useMutation({
    mutationFn: async ({ content, references, document }: { content: string; references: AgentReference[]; document: JSONContent }) => {
      let targetId = activeSession?.id;
      if (!targetId) {
        const created = await createAgentSession({ workspace_id: workspace.id });
        targetId = created.id;
        setSessionId(created.id);
        window.localStorage.setItem(sessionKey, created.id);
      }
      const message = await sendAgentMessage(targetId, { content, context: noteAttach.context, references, body_document: document });
      return { message, targetId };
    },
    onSuccess: ({ targetId }, _content, _ctx) => {
      setDraft(emptyDocument);
      noteAttach.clear();
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspace.id] });
      void attachStream(targetId);
    },
  });


  // Reconnect to an in-flight turn (e.g. after switching sessions or reload).
  React.useEffect(() => {
    if (running && activeSession) void attachStream(activeSession.id);
  }, [running, activeSession, attachStream]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    // `running` is deliberately NOT a guard any more: a message typed while the agent works
    // is a correction, and the backend injects it into the running turn (pi steering queue).
    if ((!draftText.trim() && attach.isEmpty && !noteAttach.hasNotes) || sendMessage.isPending) return;
    stick.scrollToBottom(); // 自己发的消息一定要看得见
    // 文本文件内联成围栏上下文、媒体编码成附件标记 —— 与工作流助手同一种拼法,
    // 于是两边发出来的气泡也长得一样。
    const fileBlock = textAttachmentBlock(attach.files, t("chatAttached"));
    let content = draftText.trim() || attach.files.map((file) => `[${t("chatAttached")} ${file.name}]`).join("\n");
    if (noteAttach.hasNotes) content += `\n${noteAttach.summary}`;
    for (const asset of attach.media) content += attachmentToken(asset);
    sendMessage.mutate({
      content: [content.trim(), fileBlock].filter(Boolean).join("\n\n"),
      references: collectReferences(draft),
      document: draft,
    });
    attach.clear();
  };

  // 回执消息里,答案已经被 `ask_user` 的工具结果记下的那些不再画 —— 同一次选择此前会紧挨着
  // 出现两遍(上面一张独立的卡,下面 ask_user 那一行展开还是它)。判据见 answerRecords:
  // 靠 question_id 对上才算,猜的话错的方向是把唯一那份痕迹也藏掉。
  const allMessages = messages.data ?? [];
  const recordedQuestions = React.useMemo(() => recordedQuestionIds(allMessages), [allMessages]);
  const visibleMessages = allMessages.filter(
    (message) => !queuedIds.has(message.id) && !isRedundantAnswerRecord(message, recordedQuestions),
  );
  const mediaGallery = React.useMemo(() => chatMediaGallery(visibleMessages), [visibleMessages]);
  //: 「N 个子代理」的数据源:历史消息的 timeline 摊平,再接上正在流的这一轮 ——
  //: 子代理跑到一半时就该在列表里(转着圈),不是等它跑完才出现。
  //: 正在查看的子代理(DSH 形态:进它自己的会话视图,面包屑返回)。换会话就退出 ——
  //: 面包屑上写的是**当前**会话的名字,挂着上一个会话的子代理只会指鹿为马。
  const [viewingSubagent, setViewingSubagent] = React.useState<SubagentRun | null>(null);
  React.useEffect(() => setViewingSubagent(null), [activeSession?.id]);

  const subagentSourceTimeline = React.useMemo(
    () => [
      ...visibleMessages.flatMap(
        (message) => (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline ?? [],
      ),
      ...(running ? streamTimeline : []),
    ],
    [visibleMessages, running, streamTimeline],
  );

  //: 会话统计用的轮次结构。和轨迹视图同一个构建函数 —— 两处各写一套的话,
  //: 底下报的「3 轮 · 23 步」和轨迹里数出来的迟早对不上。
  const statsTurns = React.useMemo(
    () => buildTurns(visibleMessages, running ? streamTimeline : [], usageEvents.data ?? []),
    [visibleMessages, running, streamTimeline, usageEvents.data],
  );

  /** 水位由会话详情**现算**给出,不从消息 payload 里翻。
   *  挂在消息上等于"必须先成功跑一轮才看得到" —— 而想知道"还能聊多久"的时刻恰恰在开口之前:
   *  刚打开旧会话、刚换过模型、上一轮失败了,这些时候都没有新的一轮可以带回这个数。 */
  const context = (session.data?.context ?? null) as ContextInfo | null;

  const compactContext = useMutation({
    mutationFn: () =>
      compactAgentSession<{ compaction: CompactionInfo | null }>(activeSession!.id),
    // 压成功了对话里会多一条整理记录,那本身就是反馈;**没得压和压失败必须说出来** ——
    // 此前两种情况都只是 loading 闪一下就没了,用户无从判断是没生效、还是不需要。
    onSuccess: (result) => {
      void messages.refetch();
      void qc.invalidateQueries({ queryKey: ["agent-session", activeSession?.id] });
      if (!result?.compaction) toast.message(t("agentCompactNothing"));
    },
    onError: (error) => toast.error(`${t("agentCompactFailed")}:${(error as Error).message}`),
  });
  // —— 可拉伸分栏(照剪辑页的模式:pointer 拖拽 + localStorage 持久化 + 边界钳制)——
  // clamp 在**读取**时也做:localStorage 里可能躺着旧版本写的越界值。
  const panels = useSidePanels("ai", AI_PANEL_BOUNDS);

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

  const narrow = useMediaMatch("(max-width: 1180px)");
  const single = useMediaMatch("(max-width: 820px)");
  const [environmentOpen, setEnvironmentOpen] = React.useState(false);
  const environmentId = React.useId();
  const toolbarRef = React.useRef<HTMLDivElement>(null);
  const [toolbarHeight, setToolbarHeight] = React.useState(56);
  React.useLayoutEffect(() => {
    const toolbar = toolbarRef.current;
    if (!toolbar) return;
    // 窄窗口工具栏可能换行；抽屉始终从它的下缘开始，保留原开关的点击区域。
    const measure = () => setToolbarHeight(toolbar.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(toolbar);
    return () => observer.disconnect();
  }, []);
  const showRight = view !== "trace" && environmentOpen && !narrow;
  // 内联 gridTemplateColumns 会覆盖 class 里的 max-[...] 回退,所以断点在 JS 里一起判:
  // 单列也显式指定,避免 matchMedia 的 ≤ 与 CSS max-width 的 < 在断点处不一致。
  const columns = single
    ? "minmax(0,1fr)"
    : showRight
      ? `${panels.left}px minmax(0,1fr) ${panels.right}px`
      : `${panels.left}px minmax(0,1fr)`;


  return (
    // 轨迹视图下右侧那栏让位:排查时要的是一行行看得清的步骤和一屏放得下的详情,
    // 而「智能体环境」是开工前的配置视图 —— 两者在同一屏上争的是同一份宽度。
    <div
      className={cn(
        "relative grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] max-[820px]:grid-cols-[minmax(0,1fr)] max-[760px]:grid-rows-[minmax(0,1fr)_auto]",
        !showRight
          ? "grid-cols-[240px_minmax(0,1fr)] max-[1180px]:grid-cols-[220px_minmax(0,1fr)]"
          : "grid-cols-[240px_minmax(0,1fr)_300px] max-[1180px]:grid-cols-[220px_minmax(0,1fr)]",
      )}
      style={{ gridTemplateColumns: columns }}
    >
      {/* 拖柄压在栏与栏之间那条分割线上 —— 和剪辑页同款。 */}
      {!single && (
        <div
          className={SIDEBAR_HANDLE_CLASS}
          style={{ left: handleOffset(panels.left) }}
          onPointerDown={panels.startDrag("left")}
        />
      )}
      {showRight && (
        <div
          className={SIDEBAR_HANDLE_CLASS}
          style={{ right: handleOffset(panels.right) }}
          onPointerDown={panels.startDrag("right")}
        />
      )}
      {/* flex 列而不是定行数的 grid:搜索框是**条件渲染**的(空列表/选择模式下不出现),
          而 `grid-rows-[auto_minmax(0,1fr)]` 一旦子元素从两个变三个,能滚的那一行就落到
          搜索框头上,列表反而掉进隐式行撑破容器。 */}
      <StudioIndex label={t("chatSessionsTitle")}>
        <SessionList
          kind="agent"
          workspaceId={workspace.id}
          sessions={sessions.data ?? []}
          loaded={sessions.isSuccess}
          activeSessionId={activeSession?.id ?? null}
          onSelect={(id) => {
            setSessionId(id);
            window.localStorage.setItem(sessionKey, id);
          }}
          onCreate={() => createSession.mutate()}
          creating={createSession.isPending}
          onDeleted={(ids) => {
            // 删掉的里面有正开着的那个,就把视图放下 —— 否则右侧还停在一个已经不存在的会话上。
            if (sessionId && ids.includes(sessionId)) {
              setSessionId(null);
              window.localStorage.removeItem(sessionKey);
            }
          }}
        />
      </StudioIndex>

      <section className="min-h-0 overflow-hidden bg-workspace-panel grid grid-rows-[auto_minmax(0,1fr)_auto]">
        {/* min-w-0:这行是 grid 子项,默认 min-width:auto —— 面包屑里的长任务名会把它撑到
            section 的 overflow-hidden 上被硬裁,而不是走内部的 truncate 省略号。 */}
        <div ref={toolbarRef} className="flex min-h-14 min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-1.5 max-[821px]:pl-14">
          {switcher}
          {viewingSubagent ? (
            <SubagentBreadcrumb
              sessionTitle={activeSession?.title || t("chatSessionsTitle")}
              run={viewingSubagent}
              onBack={() => setViewingSubagent(null)}
            />
          ) : (
          <>
          {/* 当前会话名常驻头部:和子代理视图的面包屑首段(父会话名)是同一个东西 ——
              进了子代理它变成面包屑的第一段,回来它就是标题本身。空会话仍保留弹性间距,分开模式与视图切换。 */}
          <span className="min-w-0 flex-1 truncate text-ui-sm font-medium text-foreground" title={activeSession?.title}>
            {activeSession?.title}
          </span>
          <div className={SEGMENTED_LIST} role="tablist" aria-label={t("chatSessionsTitle")}>
            {(["chat", "trace"] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={view === item}
                onClick={() => setView(item)}
                className={segmentedTriggerClass(view === item)}
              >
                {t(item === "chat" ? "chatTabConversation" : "chatTabTrace")}
              </button>
            ))}
          </div>
          </>
          )}
          {view === "chat" && <Button variant={environmentOpen ? "secondary" : "ghost"} size="icon-sm" aria-label={t("studioChatEnvironment")} title={t("studioChatEnvironment")} aria-pressed={environmentOpen} aria-expanded={environmentOpen} aria-controls={environmentOpen ? environmentId : undefined} onClick={() => setEnvironmentOpen(!environmentOpen)}><PanelRight /></Button>}
          {/* 「N 个子代理」:这个会话派出过的子智能体入口(DSH 同款位置)。没派过就不渲染。 */}
          {!viewingSubagent && (
            <span className="shrink-0 empty:hidden">
              <SubagentButton timeline={subagentSourceTimeline} onOpen={setViewingSubagent} />
            </span>
          )}
        </div>
        {/* 生成页同款:没有会话也常驻输入框,空状态居中在消息区,首次发送自动建会话。
            输入框在两个视图下都在 —— 看轨迹时想到要补一句,不该先切回对话。
            查看子代理时整个主区换成它的会话视图(无输入框:它的进程已结束,不可继续 ——
            装一个发不出去的输入框比没有更糟)。 */}
        {viewingSubagent ? (
          <SubagentSessionView run={viewingSubagent} workspaceId={workspace.id} />
        ) : (
          <>
            {view === "trace" ? (
              <TraceView
                messages={visibleMessages}
                streamTimeline={running ? streamTimeline : []}
                usageEvents={usageEvents.data ?? []}
              />
            ) : (
            /* 横向和纵向一起锁:flex 子项默认 min-width:auto,一段长代码块或长 URL 会把这一列
                 撑宽,整个对话区就能左右滚。代码块自己的 overflow-x-auto 只在父容器被约束时生效。 */
            <div className="relative grid min-h-0 min-w-0">
            <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-2.5 pt-7" ref={stick.ref}>
              {visibleMessages.map((message) => (
                <ChatBubble
                  key={message.id}
                  message={message}
                  workspaceId={workspace.id}
                  usageEvents={usageByMessage.get(message.id) ?? []}
                  mediaGallery={mediaGallery}
                />
              ))}
              {running && streamText && (
                <div className="relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]">
                  <AgentTurnContent timeline={streamTimeline} />
                  <AgentStatusRow className="mt-1.5" meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))} />
                </div>
              )}
              {running && !streamText && (
                <div className="relative mx-auto flex w-full max-w-[780px] shrink-0 flex-col items-stretch gap-[7px] text-ui-md leading-[1.65] text-muted-foreground [word-break:break-word]">
                  <AgentTurnContent timeline={streamTimeline} />
                  <AgentStatusRow label={t("chatThinking")} meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))} />
                </div>
              )}
              {/* **「还没读到」和「读过了,是空的」必须分开。**
                  此前这里只看 `length === 0`,而读取中 `data` 是 undefined —— 于是打开一条有
                  几十轮历史的会话时,先给你看一屏「开始新对话」的欢迎页,几秒后消息才顶进来。
                  那不是"少了个 loading",是**显示了相反的状态**:它在说这条会话是空的。 */}
              {sessionLoading && !running && (
                <div className="m-auto w-full max-w-[780px]">
                  <LoadingState label={t("chatLoadingSession")} />
                </div>
              )}
              {!sessionLoading && (messages.data ?? []).length === 0 && !running && (
                <div className="m-auto w-full max-w-[780px]">
                  <div className="mx-auto max-w-xl px-6 py-10">
                    <Sparkles className="mb-6 size-9 text-primary" strokeWidth={1.4} />
                    <h2 className="text-3xl font-semibold leading-tight tracking-tight">{t("studioChatStart")}</h2>
                    <p className="mb-8 mt-4 max-w-[42ch] text-ui-md leading-relaxed text-muted-foreground">{t("studioChatIntro")}</p>
                    <div className="flex flex-wrap gap-2">{(["Media", "Edit", "Workflow"] as const).map(kind => <Button key={kind} variant="outline" className="h-auto whitespace-normal py-3 text-left" onClick={() => setDraft({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: t(`studioPrompt${kind}Text`) }] }] })}>{t(`studioPrompt${kind}`)}</Button>)}</div>
                  </div>
                </div>
              )}
              {sessionId && <InlineConfirmations workspaceId={workspace.id} allowKey={sessionId} />}
              {sessionId && <InlineQuestions sessionId={sessionId} />}
            </div>
            <JumpToLatest stick={stick} label={t("chatJumpToLatest")} newLabel={t("chatNewBelow")} />
            </div>
            )}
            {/* Pending strip, above the composer: these have not been sent yet, so they do not
                belong in the transcript. Each one can be steered into the running turn or
                dropped — the Codex arrangement. */}
            <QueuedMessages
              messages={queue.data ?? []}
              /* 和下面那个 form 同一个宽度表达式 —— 窗口一窄两个盒子必须一起缩。 */
              className={COMPOSER_COLUMN}
              onSteer={(id) => steerQueued.mutate(id)}
              onCancel={(id) => cancelQueued.mutate(id)}
              steering={steerQueued.isPending}
              cancelling={cancelQueued.isPending}
            />
            <form
              className={cn(COMPOSER_COLUMN, "mb-3.5 mt-1.5 flex flex-col gap-1 rounded-lg border border-border bg-control pb-1.5 pl-3 pr-2.5 pt-2.5 transition-colors duration-100 focus-within:border-ring")}
              onSubmit={submit}
            >
              {/* 附件条属于输入框内部(文本框上方),而不是飘在圆角框外的左上角。 */}
              {/* 附件和笔记引用是同一件事:这条消息里带了什么。一排,在输入卡里。 */}
              <ComposerChips chips={[...attach.chips, ...noteAttach.chips]} uploading={attach.uploading} className="px-0.5" />
              {noteAttach.dialog}
              {/* `@` 唤起素材 / 笔记 / 画板 / 工作流。和画布助手共用一份 —— 同一个输入框在两个
                  地方能力不同的话,用户没有任何办法预期哪个能干什么(附件那条也是这个理由)。 */}
              <ChatComposer
                workspaceId={workspace.id}
                value={draft}
                onChange={setDraft}
                onSubmit={() => submit(new Event("submit") as unknown as React.FormEvent)}
                onPaste={attach.onPaste}
                placeholder={t("chatPlaceholder")}
                className="min-h-11"
              />
              <div className="flex items-center justify-between gap-1.5 pt-0.5">
                <div className="flex items-center gap-1.5">
                  {noteAttach.trigger}
                  {/* 28px —— 和画布助手那一行同一个刻度。见那边的说明。 */}
                  <Button asChild variant="ghost" size="icon-xs" aria-label={t("attachFile")} disabled={attach.uploading}>
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
                      {attach.uploading ? <Loader2 size={14} className="animate-mosael-spin" /> : <Paperclip size={14} />}
                    </label>
                  </Button>
                  {/* 和工作区助手共用同一个组件:两边各写一份的话,位置、顺序、有无迟早不一致。 */}
                  <DictateButton
                    onText={(text) =>
                      setDraft((current) => appendText(current, text))
                    }
                  />
                  {/* 免提不在这一行:它是"手离开键盘"的模式,而工具行只在助手面板打开时才在屏幕上 ——
                      恰好在最需要它的时候不见了。改成应用级的浮标(features/agent/VoiceDock),
                      由设置里的开关决定浮不浮。说话输入留着:那个是"把话填进这个框",本来就属于这里。 */}
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
                    disabled={(!draftText.trim() && attach.isEmpty && !noteAttach.hasNotes) || attach.uploading} loading={sendMessage.isPending}
                  >
                    <Send size={15} />
                  </Button>
                )}
              </div>
            </form>
            {/* 会话体征常驻在输入框下方,两个视图都在 —— 此前它挂在轨迹列表底部,随内容滚、
                只有轨迹页有。宽度和输入框同一个公式,左右边缘对齐;px-3 让文字对上输入框的
                圆角内缘,而不是顶着圆角外壳。 */}
            <TraceStatsBar
              turns={statsTurns}
              usageEvents={usageEvents.data ?? []}
              className={cn(COMPOSER_COLUMN, "-mt-2 mb-2 px-3")}
            />
          </>
        )}
      </section>

      {view === "chat" && environmentOpen && <div id={environmentId}
        className={cn("min-h-0 min-w-0 overflow-hidden border-l border-divider bg-workspace-subtle", narrow && "workspace-overlay absolute bottom-0 right-0 z-30 w-[min(360px,100%)]")}
        style={narrow ? { top: toolbarHeight } : undefined}
      ><ChatInspector
        headerHeight={narrow ? 56 : toolbarHeight}
        workspace={workspace}
        session={session.data ?? activeSession}
        messages={visibleMessages}
        queue={queue.data ?? []}
        running={running}
        elapsedSeconds={elapsedSeconds}
        streamTimeline={streamTimeline}
        manifest={manifest.data ?? null}
        tools={tools.data ?? []}
        subagentTimeline={subagentSourceTimeline}
        onOpenSubagent={setViewingSubagent}
      /></div>}
    </div>
  );
}

function ChatInspector({
  headerHeight,
  workspace,
  session,
  messages,
  queue,
  running,
  elapsedSeconds,
  streamTimeline,
  manifest,
  tools,
  subagentTimeline,
  onOpenSubagent,
}: {
  headerHeight: number;
  workspace: Workspace;
  session: AgentSession | null;
  messages: AgentMessage[];
  queue: AgentMessage[];
  running: boolean;
  elapsedSeconds: number;
  streamTimeline: AgentTimelineItem[];
  manifest: AgentManifest | null;
  tools: AgentTool[];
  subagentTimeline: AgentTimelineItem[];
  onOpenSubagent: (run: SubagentRun) => void;
}) {
  const t = useI18n();
  // 会话没显式设模型时,后端按供应商默认回退——与底部模型选择器同源,取生效模型而不是裸 session.model
  // (否则这里显示 —,底部却显示 deepseek-v4-pro,对不上)。
  const effectiveModel = useEffectiveChatModel(session).model;
  // 历次计划:从消息时间线里的 update_plan 调用还原(见 PlanCard.planHistory)。
  const plans = React.useMemo(
    () => planHistory(messages.map((message) => (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline)),
    [messages],
  );
  const recentTools = React.useMemo(
    () => collectRecentToolCalls(messages, running ? streamTimeline : []).slice(0, 6),
    [messages, running, streamTimeline],
  );
  const [toolBrowser, setToolBrowser] = React.useState(false);
  // 「最近工具」和「任务计划」一样可以收成一行 —— 侧栏里三块常驻,
  // 不看的时候能折起来才谈得上"看得下去"。
  const [toolsOpen, setToolsOpen] = React.useState(true);
  const failedCount = messages.filter((message) => message.error).length;
  const status = session?.status ?? (running ? "running" : "idle");
  const statusLabel = running
    ? `${t("agentStatusRunning")} · ${elapsedSeconds}s`
    : status === "idle"
      ? t("agentStatusIdle")
      : status;

  return (
    <aside
      className="flex h-full min-h-0 min-w-0 flex-col"
      aria-label={t("agentInspectorTitle")}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-divider px-4" style={{ height: headerHeight }}>
        <h2 className="m-0 text-ui-sm font-semibold">{t("agentInspectorTitle")}</h2>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 text-ui-xs tabular-nums text-muted-foreground",
            running && "text-primary",
          )}
        >
          <CircleDot size={10} /> {statusLabel}
        </span>
      </div>

      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 overflow-y-auto overflow-x-hidden p-4">

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
      <PlanCard plan={(session?.plan ?? null) as PlanStep[] | null} history={plans} />

      {/* 子代理排在计划之后、工具之前:它是"派出去的活",粒度介于计划和单次调用之间。
          没派过就不渲染 —— 和计划同一条规矩。 */}
      <InspectorSubagentList timeline={subagentTimeline} onOpen={onOpenSubagent} />

      {/* 「最近工具」与「能力」原本是两块 —— 一块只有名字和状态(看不出做了什么),另一块把
          36 个工具铺成四行胶囊(占掉半个侧栏,而那 8 个只是注册表顺序的前 8 个)。
          合成一块:头部一行交代规模与版本,主体是可展开看参数/结果的最近调用,
          全部工具收进一个带搜索的弹层——要查一个工具能干嘛时才打开。 */}
      <InspectorCard
        icon={Wrench}
        title={t("agentInspectorRecentTools")}
        onToggle={() => setToolsOpen((value) => !value)}
        open={toolsOpen}
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
        {!toolsOpen ? null : recentTools.length > 0 ? (
          // gap-1 和「任务计划」同一个节奏。此前这里没有 gap、靠每行一条 border-b 分开 ——
          // **分隔线是在补缺失的间距**,而它又是整个检查器里唯一一处横线,三块并排就格格不入。
          // gap-0.5 + 更浅的行内边距:这是一列"扫一眼"的记录,不是需要逐条阅读的内容,
          // 行与行贴近反而更好数。
          <ul className="m-0 grid list-none gap-0.5 p-0">
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
      </div>
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
        className="-mx-1 grid min-h-8 min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md border-0 bg-transparent px-1 py-1.5 text-left text-ui-xs text-foreground transition-colors hover:bg-secondary"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <AgentStatusIcon status={toAgentStatus(call.status)} />
        <ToolName name={call.name} className="text-ui-xs font-normal" />
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

export function ToolBrowserRow({ tool }: { tool: AgentTool }) {
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
        {/* 工具说明是写给模型看的,常带 `代码` 和 **强调**;在按钮里,链接只留文字。 */}
        <InlineMarkdown text={tool.description} links={false} />
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
    ? tools.filter((tool) => `${tool.name} ${toPlainText(tool.description)}`.toLowerCase().includes(needle))
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
