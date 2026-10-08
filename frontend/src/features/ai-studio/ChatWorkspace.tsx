import { useNoteAttachments } from "@/features/notes/useNoteAttachments";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import React from "react";
import { StudioIndex } from "@/components/layout/StudioIndex";
import { useWriteBlocked } from "@/components/layout/useWriteBlocked";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, CircleDot, Database, Eye, Loader2, PanelRight, Paperclip, SearchX, Send, Sparkles, Square, Wrench } from "lucide-react";
import { toast } from "sonner";

import {
  agentManifest,
  compactAgentSession,
  dropQueuedMessage,
  getAgentSession,
  listAgentMessages,
  listAgentQueue,
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
import { transcriptPolling, useTranscriptFollowsSession } from "@/features/agent/transcriptFollowsSession";
import { MAX_MESSAGE_CHARS, textAttachmentBlock, useComposerAttachments } from "@/features/agent/composerAttachments";
import { ComposerChips } from "@/features/agent/ComposerChips";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Truncate } from "@/components/ui/truncate";
import type { JSONContent } from "@tiptap/react";

import { appendText, collectReferences, emptyDocument } from "@/features/agent/ChatComposer";
import { DraftBlank, DraftComposer, useComposerDraft } from "@/features/agent/composerDraft";
import { collectSkills } from "@/features/agent/SkillChip";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import type { AgentReference } from "@/features/agent/references";
import { ModalShell } from "@/components/app/modals";
import { AgentStatusRow } from "@/features/agent/AgentStatusRow";
import { ChatBubble } from "@/features/agent/ChatBubble";
import { ChatTranscriptSkeleton } from "@/features/agent/chatSkeleton";
import { isWaitingReceipt } from "@/features/agent/JobReceiptNotice";
import { SessionList } from "@/features/ai-studio/SessionList";
import { attachmentToken, chatMediaGallery } from "@/features/agent/userMessage";
import { type AgentUsageEvent } from "@/features/agent/messageUsage";
import { EmptyState } from "@/components/layout/EmptyState";
import { DictateButton } from "@/features/agent/DictateButton";
import { ModelPicker } from "@/features/agent/ModelPicker";
import { SessionSettingsMenu } from "@/features/agent/SessionSettingsMenu";
import { AGENT_DRAFT_EVENT, useAgentSessions, useCurrentAgentSession } from "@/features/agent/currentAgentSession";
import { canGoHome, openedIn } from "@/features/agent/homeLabel";
import { STUDIO_PLACE, placePayload } from "@/features/agent/places";
import { goHome } from "@/features/ai-studio/goToPlace";
import { workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";
import { useOpenRequest } from "@/lib/deepLink";
import { type CompactionInfo, type ContextInfo } from "@/features/agent/ContextMeter";
import { InspectorCard, InspectorRow } from "@/components/layout/InspectorCard";
import { PlanCard, planHistory, type PlanStep } from "@/features/agent/PlanCard";
import { useStickToBottom } from "@/features/agent/stickToBottom";
import { QueuedMessages } from "@/features/agent/QueuedMessages";
import { JumpToLatestOrDecision, PendingDecisions, SessionDecisions } from "@/features/agent/PendingDecisions";
import { isRedundantAnswerRecord, recordedQuestionIds } from "@/features/agent/answerRecords";
import { AgentTurnContent, toolCallIds, type AgentTimelineItem, type ToolCall } from "@/features/agent/ToolCalls";
import { formatElapsedSeconds } from "@/lib/time";
import { AgentStatusIcon, ToolName, toAgentStatus } from "@/features/agent/StatusIcon";
import { readToolPayload } from "@/features/ai-studio/toolPayload";
import { TraceStatsBar, TraceView } from "@/features/agent/trace/TraceView";
import { buildTurns } from "@/features/agent/trace/traceModel";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { SIDEBAR_HANDLE_CLASS, handleOffset, useSidePanels } from "@/lib/useResizableSidebar";
import { InspectorSubagentList, SubagentBreadcrumb, SubagentButton, SubagentSessionView, collectSubagentRuns, type SubagentRun } from "@/features/agent/SubagentPanel";
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
/** 轨迹 / 子代理视图:对话里的工具行不在屏上,待决的卡全摆在输入框上方。 */
const NOTHING_PLACED: ReadonlySet<string> = new Set();
/** 没有用量的那些气泡共用这一份:每次渲染新给一个 `[]`,气泡的 memo 就永远对不上(FA-04)。 */
const NO_USAGE: AgentUsageEvent[] = [];
const NO_MESSAGES: AgentMessage[] = [];

export function ChatWorkspace({
  workspace,
  switcher,
}: {
  workspace: Workspace;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const writeBlocked = useWriteBlocked(workspace.role);
  // AI Studio 这一处的当前对话、选择、草稿、删后回到草稿:和免提浮标、页面跳转在这一处时读的是同一份(见 currentAgentSession)。
  // 列表列全部(每行写着在哪开的);点开哪段,就是在 AI Studio 接着它,它的家不变(ADR 0044 §5)。
  const current = useCurrentAgentSession(workspace.id, STUDIO_PLACE);
  const everything = useAgentSessions(workspace.id, { pollList: 4000 });
  const activeSession = current.session;
  //: 同事共享来的对话**只能看**(判据在 currentAgentSession.isViewOnly):输入区换成一句只读说明 —— 模型、
  //: 会话设置、附件都在输入区里,一起不给;排队条、停止、拍板的按钮也是主人的。消息、轨迹、花费照看。
  const readOnly = current.readOnly;
  //: 草稿是**编辑器文档**,不是字符串 —— `@` 出来的引用是原子节点(见 ChatComposer)。
  //: 它**不是这里的状态**:这一层不订阅它,打字只重渲输入框和发送键,不重渲整段对话(见 composerDraft,FA-04)。
  //: 这一层只在发送、填入、清空的那一刻读写。
  const draft = useComposerDraft();
  // 从别处带着一段话来(内嵌浏览器顶栏「交给智能体」):填进输入框,一行一段,不替他发送。
  useOpenRequest(AGENT_DRAFT_EVENT, (text) => {
    draft.set({
      type: "doc",
      content: text.split("\n").map((line) => (line ? { type: "paragraph", content: [{ type: "text", text: line }] } : { type: "paragraph" })),
    });
  });
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
  const { streamText, streamTimeline, attach: attachStream } = useAgentTurnStream(activeSession?.id ?? null);
  //「对话」读答案,「轨迹」读执行。记住选择:排查问题的人往往连着看好几个会话的轨迹。
  const [view, setView] = usePersistentTab<"chat" | "trace">("agent-view", "chat", ["chat", "trace"]);

  //: 贴底跟随。resetKey 用会话 id:换会话该从底部重新开始。
  const stick = useStickToBottom<HTMLDivElement>(activeSession?.id);

  const session = useQuery({
    queryKey: ["agent-session", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => getAgentSession(activeSession!.id),
    refetchInterval: 1200,
    refetchOnWindowFocus: true,
  });
  const running = session.data?.status === "running";
  //: 消息只在跑着的时候轮询;空闲时跟着会话的状态 / updated_at 变化重取一次(见 transcriptFollowsSession)—— 此前每 1.2 秒
  //: 无条件整段重拉,一段带着工具结果的长对话就是每秒几 MB。
  const messages = useQuery({
    queryKey: ["agent-messages", activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () => listAgentMessages(activeSession!.id),
    refetchInterval: transcriptPolling(running),
    refetchOnWindowFocus: true,
  });
  useTranscriptFollowsSession(activeSession?.id ?? "", session.data);
  //: 会话清单还在路上,或者选中的这条会话的消息还在路上。两者都不算"这条会话是空的"。
  //: `enabled` 为假时 React Query 的 status 也是 pending,所以要先确认真的有一条会话在读。
  const sessionLoading = current.resolving || (Boolean(activeSession) && messages.isPending);
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
  const queuedIds = React.useMemo(
    () => new Set((running ? queue.data ?? [] : []).map((message) => message.id)),
    [running, queue.data],
  );
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

  // 发送时没有会话就先建一个(生成页同款「输入框直达」交互)。
  const sendMessage = useMutation({
    mutationFn: async ({ content, references, document }: { content: string; references: AgentReference[]; document: JSONContent }) => {
      const targetId = (await current.ensure()).id;
      //: 「/」点名的技能(ADR 0040 §4)跟着这条消息走,后端把全文挂到这一轮。
      const skills = collectSkills(document);
      const message = await sendAgentMessage(targetId, {
        content, context: noteAttach.context, references, body_document: document, ...(skills.length ? { skills } : {}),
        place: placePayload(STUDIO_PLACE),
      });
      return { message, targetId };
    },
    onSuccess: ({ targetId }, _content, _ctx) => {
      draft.set(emptyDocument);
      noteAttach.clear();
      // 附件在发出去之后才清 —— 此前 mutate 一调就清,发送失败时附件跟着丢了(画布助手一直是这样)。
      attach.clear();
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
    const draftText = draft.text();
    if ((!draftText.trim() && attach.isEmpty && !noteAttach.hasNotes) || sendMessage.isPending) return;
    stick.scrollToBottom(); // 自己发的消息一定要看得见
    // 文本文件内联成围栏上下文、媒体编码成附件标记 —— 与工作流助手同一种拼法,
    // 于是两边发出来的气泡也长得一样。
    const fileBlock = textAttachmentBlock(attach.files, t("chatAttached"));
    let content = draftText.trim() || attach.files.map((file) => `[${t("chatAttached")} ${file.name}]`).join("\n");
    if (noteAttach.hasNotes) content += `\n${noteAttach.summary}`;
    for (const asset of attach.media) content += attachmentToken(asset);
    const full = [content.trim(), fileBlock].filter(Boolean).join("\n\n");
    //: 先在这里说,不等后端回一句英文的「at most 8000 characters」(见 composerAttachments 的 MAX_MESSAGE_CHARS)。
    if (full.length > MAX_MESSAGE_CHARS) {
      toast.error(t("composerMessageTooLong"));
      return;
    }
    sendMessage.mutate({
      content: full,
      references: collectReferences(draft.get()),
      document: draft.get(),
    });
  };

  // 回执消息里,答案已经被 `ask_user` 的工具结果记下的那些不再画 —— 同一次选择此前会紧挨着
  // 出现两遍(上面一张独立的卡,下面 ask_user 那一行展开还是它)。判据见 answerRecords:
  // 靠 question_id 对上才算,猜的话错的方向是把唯一那份痕迹也藏掉。
  //: 这一串都要 memo:气泡是 memo 的(ChatBubble),这里每次渲染派生一个新数组,画廊跟着变,三百个气泡就全部重画。
  const allMessages = messages.data ?? NO_MESSAGES;
  const recordedQuestions = React.useMemo(() => recordedQuestionIds(allMessages), [allMessages]);
  const visibleMessages = React.useMemo(
    () => allMessages.filter((message) => !queuedIds.has(message.id) && !isRedundantAnswerRecord(message, recordedQuestions)),
    [allMessages, queuedIds, recordedQuestions],
  );
  const mediaGallery = React.useMemo(() => chatMediaGallery(visibleMessages), [visibleMessages]);
  //: 还没交给智能体的回执不算进对话记录(轨迹、统计):它们这一轮结束才交出去,在那之前画在正在跑的那一轮下面。
  const transcriptMessages = React.useMemo(
    () => visibleMessages.filter((message) => !isWaitingReceipt(message)),
    [visibleMessages],
  );
  const waitingReceipts = visibleMessages.filter(isWaitingReceipt);
  //: 「N 个子代理」的数据源:历史消息的 timeline 摊平,再接上正在流的这一轮 ——
  //: 子代理跑到一半时就该在列表里(转着圈),不是等它跑完才出现。
  //: 正在查看的子代理(DSH 形态:进它自己的会话视图,面包屑返回)。换会话就退出 ——
  //: 面包屑上写的是**当前**会话的名字,挂着上一个会话的子代理只会指鹿为马。
  //: 只记**是哪一次调用**,不记点开那一刻的快照 —— 快照会把一个还在跑的子代理永远冻在「正在调查…」,
  //: 跑完了也不变。每次渲染按 id 从时间线里重新取,状态和存档跟着回填走。
  const [viewingSubagentId, setViewingSubagentId] = React.useState<string | null>(null);
  React.useEffect(() => setViewingSubagentId(null), [activeSession?.id]);
  const openSubagent = (run: SubagentRun) => setViewingSubagentId(run.call.id);

  const subagentSourceTimeline = React.useMemo(
    () => [
      ...visibleMessages.flatMap(
        (message) => (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline ?? [],
      ),
      ...(running ? streamTimeline : []),
    ],
    [visibleMessages, running, streamTimeline],
  );
  const viewingSubagent = React.useMemo(
    () => (viewingSubagentId ? collectSubagentRuns(subagentSourceTimeline).find((run) => run.call.id === viewingSubagentId) ?? null : null),
    [viewingSubagentId, subagentSourceTimeline],
  );
  //: 有输入框的时候才收拖进来的文件(见下面 section 上那段说明)。
  const acceptsFiles = !readOnly && !viewingSubagent;

  //: 会话统计用的轮次结构。和轨迹视图同一个构建函数 —— 两处各写一套的话,
  //: 底下报的「3 轮 · 23 步」和轨迹里数出来的迟早对不上。
  const statsTurns = React.useMemo(
    () => buildTurns(transcriptMessages, running ? streamTimeline : [], usageEvents.data ?? []),
    [transcriptMessages, running, streamTimeline, usageEvents.data],
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

  //: 等你拍板的卡(确认 / 选择)不跟着视图走。对话视图里确认卡摆在发起它的那次工具调用里(对不上任何一行的
  //: 和选择卡在消息流末尾);看轨迹、看子代理时消息流不在屏上,它们就全停在输入框上方 —— 此前两张卡只写在
  //: 对话分支里,一切到轨迹就卸载:确认卡掉回右上角的全局中心(少了「本会话始终允许」),选择卡哪儿都看不到,
  //: 智能体干等到超时。
  const pendingCards = activeSession ? (
    <div className={cn(COMPOSER_COLUMN, "grid max-h-[40vh] min-w-0 gap-2 overflow-y-auto overflow-x-hidden empty:hidden")}>
      <PendingDecisions placed={NOTHING_PLACED} />
    </div>
  ) : null;
  //: 对话视图里画出来的工具调用:对得上其中一行的确认卡就摆在那一行里。
  const placedToolCalls = toolCallIds([
    ...visibleMessages.map((message) => (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline),
    running ? streamTimeline : [],
  ]);
  //: 装着这段对话的那一块 —— 「有请求等你确认」在它里面找那张卡。
  const threadArea = React.useRef<HTMLDivElement | null>(null);

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
  const showRight = environmentOpen && !narrow;
  // 内联 gridTemplateColumns 会覆盖 class 里的 max-[...] 回退,所以断点在 JS 里一起判:
  // 单列也显式指定,避免 matchMedia 的 ≤ 与 CSS max-width 的 < 在断点处不一致。
  const columns = single
    ? "minmax(0,1fr)"
    : showRight
      ? `${panels.left}px minmax(0,1fr) ${panels.right}px`
      : `${panels.left}px minmax(0,1fr)`;


  return (
    // 右侧「智能体环境」在对话、轨迹两个视图下都能开:此前轨迹视图替人把它收掉、连开关都藏了,
    // 排查时想对照这个会话用的模型、工具就只能切回对话。宽度紧的话自己点开关收起。
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
          sessions={everything.data ?? []}
          loaded={everything.isSuccess}
          activeSessionId={activeSession?.id ?? null}
          onSelect={current.select}
          onCreate={current.startDraft}
          creating={false}
          writeBlocked={writeBlocked}
          onDeleted={current.forget}
          //: 家在 AI Studio 的不写(每行都说「在 AI Studio 里开的」只是噪音);回得去的给一颗「回到那里」。
          extras={(item) =>
            item.home_kind === "studio"
              ? null
              : {
                  subtitle: openedIn(t, item),
                  goBack: canGoHome(item) && (item.home_kind !== "comfyui" || workbenchAvailable())
                    ? {
                        label: t("agentGoHome"),
                        hint: t("agentGoHomeHint"),
                        onClick: () => void Promise.resolve(goHome(workspace.id, item)).catch((error: Error) => toast.error(error.message)),
                      }
                    : undefined,
                }
          }
        />
      </StudioIndex>

      {/* 文件拖到整块对话区上都算数(输入框只有两行高,瞄准它松手太难)。只读、看子代理时没有输入框,
          也就没有附件可加 —— 那时不接拖放,不亮一个松手后什么都不会发生的提示。 */}
      <section
        className="relative min-h-0 overflow-hidden bg-workspace-panel grid grid-rows-[auto_minmax(0,1fr)_auto]"
        {...(acceptsFiles ? attach.drop.handlers : {})}
      >
        {/* 确认卡跟着对话走:取卡、拍板在这一层,对话里每一次工具调用的那一行各自查自己的卡(见 PendingDecisions)。 */}
        <SessionDecisions workspaceId={workspace.id} sessionId={activeSession?.id ?? null} readOnly={readOnly} live={running}>
        {acceptsFiles && attach.drop.overlay}
        {/* min-w-0:这行是 grid 子项,默认 min-width:auto —— 面包屑里的长任务名会把它撑到
            section 的 overflow-hidden 上被硬裁,而不是走内部的 truncate 省略号。 */}
        <div ref={toolbarRef} className="flex min-h-14 min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-1.5 max-[821px]:pl-14">
          {switcher}
          {viewingSubagent ? (
            <SubagentBreadcrumb
              sessionTitle={activeSession?.title || t("chatSessionsTitle")}
              run={viewingSubagent}
              onBack={() => setViewingSubagentId(null)}
            />
          ) : (
          <>
          {/* 当前会话名常驻头部:和子代理视图的面包屑首段(父会话名)是同一个东西 ——
              进了子代理它变成面包屑的第一段,回来它就是标题本身。空会话仍保留弹性间距,分开模式与视图切换。 */}
          <Truncate className="flex-1 text-ui-sm font-medium text-foreground">{activeSession?.title}</Truncate>
          <div className={segmentedListClass()} role="tablist" aria-label={t("chatSessionsTitle")}>
            {(["chat", "trace"] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={view === item}
                onClick={() => setView(item)}
                className={segmentedItemClass(view === item)}
              >
                {t(item === "chat" ? "chatTabConversation" : "chatTabTrace")}
              </button>
            ))}
          </div>
          </>
          )}
          <IconButton variant={environmentOpen ? "secondary" : "ghost"} size="icon-sm" label={t("agentInspectorTitle")} aria-pressed={environmentOpen} aria-expanded={environmentOpen} aria-controls={environmentOpen ? environmentId : undefined} onClick={() => setEnvironmentOpen(!environmentOpen)}><PanelRight /></IconButton>
          {/* 「N 个子代理」:这个会话派出过的子智能体入口(DSH 同款位置)。没派过就不渲染。 */}
          {!viewingSubagent && (
            <span className="shrink-0 empty:hidden">
              <SubagentButton timeline={subagentSourceTimeline} onOpen={openSubagent} />
            </span>
          )}
        </div>
        {/* 生成页同款:没有会话也常驻输入框,空状态居中在消息区,首次发送自动建会话。
            输入框在两个视图下都在 —— 看轨迹时想到要补一句,不该先切回对话。
            查看子代理时整个主区换成它的会话视图。**没有输入框**:子代理不接受续聊,装一个发不出去
            的输入框比没有更糟。**但父会话的这一轮可能还在跑**(子代理正是它派出去的),这时底部
            留一条「父会话运行中 · 停止」—— 否则想停只能先退出子代理视图。 */}
        {viewingSubagent ? (
          <>
            <SubagentSessionView run={viewingSubagent} workspaceId={workspace.id} />
            {pendingCards}
            {running && (
              <div className={cn(COMPOSER_COLUMN, "mb-3.5 mt-1.5 flex min-w-0 items-center gap-2 rounded-lg border border-border bg-control py-1 pl-3 pr-1.5")}>
                <AgentStatusRow
                  className="min-w-0 flex-1"
                  label={t("chatParentRunning")}
                  meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))}
                />
                {!readOnly && (
                  <Button
                    variant="outline"
                    size="xs"
                    className="shrink-0"
                    loading={stopTurn.isPending}
                    onClick={() => stopTurn.mutate()}
                  >
                    <Square size={11} fill="currentColor" />
                    {t("chatStop")}
                  </Button>
                )}
              </div>
            )}
          </>
        ) : (
          <>
            {view === "trace" ? (
              <TraceView
                key={activeSession?.id ?? "none"}
                messages={transcriptMessages}
                streamTimeline={running ? streamTimeline : []}
                usageEvents={usageEvents.data ?? []}
                loading={sessionLoading && !running}
                runningLabel={running ? t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds)) : null}
              />
            ) : (
            /* 横向和纵向一起锁:flex 子项默认 min-width:auto,一段长代码块或长 URL 会把这一列
                 撑宽,整个对话区就能左右滚。代码块自己的 overflow-x-auto 只在父容器被约束时生效。 */
            <div className="relative grid min-h-0 min-w-0" ref={threadArea}>
            <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-2.5 pt-7" ref={stick.ref}>
              {transcriptMessages.map((message) => (
                <ChatBubble
                  key={message.id}
                  message={message}
                  workspaceId={workspace.id}
                  usageEvents={usageByMessage.get(message.id) ?? NO_USAGE}
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
                  {/* 整理上下文的那几十秒这段对话也是占着的(和一轮同一个认领,见 host.compact_session_context):说它在整理,不说在思考。 */}
                  <AgentStatusRow label={t(compactContext.isPending ? "agentCompactRunning" : "chatThinking")} meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))} />
                </div>
              )}
              {/* **「还没读到」和「读过了,是空的」必须分开。**
                  此前这里只看 `length === 0`,而读取中 `data` 是 undefined —— 于是打开一条有
                  几十轮历史的会话时,先给你看一屏「开始新对话」的欢迎页,几秒后消息才顶进来。
                  那不是"少了个 loading",是**显示了相反的状态**:它在说这条会话是空的。 */}
              {/* 还没读到:摆真气泡外壳的骨架(用户气泡、助手那一轮),消息到了原地换上 —— 不在正中间转圈 */}
              {sessionLoading && !running && (
                <>
                  <span role="status" className="sr-only">{t("chatLoadingSession")}</span>
                  <ChatTranscriptSkeleton />
                </>
              )}
              {!sessionLoading && (messages.data ?? []).length === 0 && !running && (
                <div className="m-auto w-full max-w-[780px]">
                  <div className="mx-auto max-w-xl px-6 py-10">
                    <Sparkles className="mb-6 size-9 text-primary" strokeWidth={1.4} />
                    <h2 className="text-3xl font-semibold leading-tight tracking-tight">{t("studioChatStart")}</h2>
                    <p className="mb-8 mt-4 max-w-[42ch] text-ui-md leading-relaxed text-muted-foreground">{t("studioChatIntro")}</p>
                    {!readOnly && <div className="flex flex-wrap gap-2">{(["Media", "Edit", "Workflow"] as const).map(kind => <Button key={kind} variant="outline" className="h-auto whitespace-normal py-3 text-left" onClick={() => draft.set({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: t(`studioPrompt${kind}Text`) }] }] })}>{t(`studioPrompt${kind}`)}</Button>)}</div>}
                  </div>
                </div>
              )}
              <PendingDecisions placed={placedToolCalls} />
              {/* 还没交给智能体的回执画在正在跑的那一轮下面:这一轮结束它才交出去,交出去之后也排在这里。 */}
              {waitingReceipts.map((message) => (
                <ChatBubble
                  key={message.id}
                  message={message}
                  workspaceId={workspace.id}
                  usageEvents={NO_USAGE}
                  mediaGallery={mediaGallery}
                />
              ))}
            </div>
            <JumpToLatestOrDecision
              stick={stick}
              label={t("chatJumpToLatest")}
              newLabel={t("chatNewBelow")}
              decisionLabel={t("chatDecisionWaiting")}
              area={threadArea}
            />
            </div>
            )}
            {view === "trace" && pendingCards}
            {readOnly ? (
              // 同事共享来的对话:只能看。不摆一个点了会被拒的输入框,说清楚为什么、怎么办(自己开一条)。
              <p
                role="note"
                className={cn(COMPOSER_COLUMN, "mb-3.5 mt-1.5 flex items-start gap-2 rounded-lg border border-dashed border-border px-3 py-2.5 text-ui-sm leading-[1.55] text-muted-foreground")}
              >
                <Eye size={14} className="mt-[3px] shrink-0" aria-hidden />
                {t("chatSessionReadOnly")}
              </p>
            ) : (
              <>
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
                  data-toast-avoid=""
                  className={cn(COMPOSER_COLUMN, "mb-3.5 mt-1.5 flex flex-col gap-1 rounded-lg border border-border bg-control pb-1.5 pl-3 pr-2.5 pt-2.5 transition-colors duration-100 focus-within:border-ring")}
                  onSubmit={submit}
                >
                  {/* 附件条属于输入框内部(文本框上方),而不是飘在圆角框外的左上角。 */}
                  {/* 附件和笔记引用是同一件事:这条消息里带了什么。一排,在输入卡里。 */}
                  <ComposerChips chips={[...attach.chips, ...noteAttach.chips]} uploading={attach.uploading} className="px-0.5" />
                  {attach.previewModal}
                  {noteAttach.dialog}
                  {/* `@` 唤起素材 / 笔记 / 画板 / 工作流。和画布助手共用一份 —— 同一个输入框在两个
                      地方能力不同的话,用户没有任何办法预期哪个能干什么(附件那条也是这个理由)。 */}
                  <DraftComposer
                    draft={draft}
                    workspaceId={workspace.id}
                    onSubmit={() => submit(new Event("submit") as unknown as React.FormEvent)}
                    onPaste={attach.onPaste}
                    placeholder={t("chatPlaceholder")}
                    className="min-h-11"
                  />
                  <div className="flex items-center justify-between gap-1.5 pt-0.5">
                    <div className="flex items-center gap-1.5">
                      {noteAttach.trigger}
                      {/* 28px —— 和画布助手那一行同一个刻度。见那边的说明。 */}
                      <IconButton asChild variant="ghost" size="icon-xs" label={t("attachFile")} disabled={attach.uploading}>
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
                      </IconButton>
                      {/* 和工作区助手共用同一个组件:两边各写一份的话,位置、顺序、有无迟早不一致。 */}
                      <DictateButton
                        onText={(text) =>
                          draft.set((current) => appendText(current, text))
                        }
                      />
                      {/* 免提不在这一行:它是"手离开键盘"的模式,而工具行只在助手面板打开时才在屏幕上 ——
                          恰好在最需要它的时候不见了。改成应用级的浮标(features/agent/VoiceDock),
                          由设置里的开关决定浮不浮。说话输入留着:那个是"把话填进这个框",本来就属于这里。 */}
                      {/* 会话详情还在读时先用清单里那份:两者是同一条会话,只差水位。 */}
                      <ModelPicker workspaceId={workspace.id} place={STUDIO_PLACE} session={session.data ?? activeSession} />
                      {/* 分析方式、思考档位、上下文整理收进这里 —— 它们是"配好就不再动"的东西,
                          和每次都要用的模式/附件/模型平铺在一起只会稀释后者。 */}
                      <SessionSettingsMenu
                        workspaceId={workspace.id}
                        place={STUDIO_PLACE}
                        session={session.data ?? activeSession}
                        context={context}
                        compacting={compactContext.isPending}
                        onCompact={running ? undefined : () => compactContext.mutate()}
                      />
                    </div>
                    {/* One button that changes meaning, the way ChatGPT does it: while the agent
                        works it stops the turn, and the moment you type something it becomes send
                        again — because then the obvious intent is to say that, not to stop. */}
                    <DraftBlank draft={draft}>
                    {(blank) => running && blank && attach.isEmpty && !noteAttach.hasNotes ? (
                      <IconButton
                        variant="default"
                        size="icon-sm"
                        className="shrink-0 rounded-full"
                        label={t("chatStop")}
                        loading={stopTurn.isPending}
                        onClick={() => stopTurn.mutate()}
                      >
                        <Square size={13} fill="currentColor" />
                      </IconButton>
                    ) : (
                      <IconButton
                        type="submit"
                        variant="default"
                        size="icon-sm"
                        className="shrink-0 rounded-full"
                        label={running ? t("chatSteer") : t("chatSend")}
                        hint={running ? t("chatSteerHint") : undefined}
                        disabled={(blank && attach.isEmpty && !noteAttach.hasNotes) || attach.uploading} loading={sendMessage.isPending}
                        disabledReason={attach.uploading ? t("composerUploading") : undefined}
                      >
                        <Send size={15} />
                      </IconButton>
                    )}
                    </DraftBlank>
                  </div>
                </form>
              </>
            )}
            {/* 会话体征常驻在输入框下方,两个视图都在 —— 此前它挂在轨迹列表底部,随内容滚、
                只有轨迹页有。宽度和输入框同一个公式,左右边缘对齐;px-3 让文字对上输入框的
                圆角内缘,而不是顶着圆角外壳。 */}
            <TraceStatsBar
              turns={statsTurns}
              usageEvents={usageEvents.data ?? []}
              pending={sessionLoading && !running}
              className={cn(COMPOSER_COLUMN, "-mt-2 mb-2 px-3")}
            />
          </>
        )}
        </SessionDecisions>
      </section>

      {environmentOpen && <div id={environmentId}
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
        onOpenSubagent={openSubagent}
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
    ? `${t("agentStatusRunning")} · ${formatElapsedSeconds(elapsedSeconds)}`
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
        <InspectorRow label={t("agentWorkspace")} value={workspace.name} />
        <InspectorRow label={t("agentModel")} value={effectiveModel || "—"} />
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
      {/* 工具说明是写给模型看的,常带 `代码` 和 **强调**;在按钮里,链接只留文字。收着时露两行,点开看全。 */}
      {open ? (
        <span className="min-w-0 break-words text-ui-xs leading-[1.5] text-muted-foreground">
          <InlineMarkdown text={tool.description} links={false} />
        </span>
      ) : (
        <Truncate lines={2} className="text-ui-xs leading-[1.5] text-muted-foreground">
          <InlineMarkdown text={tool.description} links={false} />
        </Truncate>
      )}
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
