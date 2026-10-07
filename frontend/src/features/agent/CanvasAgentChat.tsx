import { useNoteAttachments } from "@/features/notes/useNoteAttachments";
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Eye,
  Move,
  PanelRight,
  Paperclip,
  Plus,
  Send,
  Square,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { useAgentTurnStream } from "@/features/agent/useAgentTurnStream";
import {
  MAX_CONTEXT_CHARS,
  MAX_MESSAGE_CHARS,
  textAttachmentBlock,
  useComposerAttachments,
} from "@/features/agent/composerAttachments";
import { ComposerChips } from "@/features/agent/ComposerChips";
import { DictateButton } from "@/features/agent/DictateButton";

import {
  type Asset,
  compactAgentSession,
  deleteAgentSession,
  dropQueuedMessage,
  getAgentSession,
  listAgentMessages,
  listAgentQueue,
  listAgentUsageEvents,
  sendAgentMessage,
  steerQueuedMessage,
  stopAgentSession,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { UserMessageContent, attachmentToken } from "@/features/agent/userMessage";
import { MessageUsageFooter, type AgentUsageEvent } from "@/features/agent/messageUsage";
import { useI18n } from "@/app/preferences";
import { LoadingState } from "@/components/layout/LoadingState";
import { IconButton } from "@/components/ui/icon-button";
import type { JSONContent } from "@tiptap/react";

import { ChatComposer, appendText, collectReferences, documentText, emptyDocument } from "@/features/agent/ChatComposer";
import { collectSkills } from "@/features/agent/SkillChip";
import type { AgentReference } from "@/features/agent/references";
import { JumpToLatestOrDecision, PendingDecisions, SessionDecisions } from "@/features/agent/PendingDecisions";
import { AgentSessionSwitcher } from "@/features/agent/AgentSessionSwitcher";
import { ModelPicker } from "@/features/agent/ModelPicker";
import { AgentErrorCard, AgentTurnContent, toolCallIds, type AgentTimelineItem } from "@/features/agent/ToolCalls";
import { AnsweredChoiceCard, type AnsweredChoice } from "@/features/agent/AnsweredChoice";
import { JOB_RECEIPT_ROLE, JobReceiptNotice, isWaitingReceipt } from "@/features/agent/JobReceiptNotice";
import { isRedundantAnswerRecord, recordedQuestionIds } from "@/features/agent/answerRecords";
import { AgentStatusRow } from "@/features/agent/AgentStatusRow";
import { useStickToBottom } from "@/features/agent/stickToBottom";
import { QueuedMessages } from "@/features/agent/QueuedMessages";
import { ConfirmDialog } from "@/components/app/modals";
import { useCurrentAgentSession } from "@/features/agent/currentAgentSession";
import { formatElapsedSeconds } from "@/lib/time";
import { CompactionNotice, type CompactionInfo, type ContextInfo } from "@/features/agent/ContextMeter";
import { SessionSettingsMenu } from "@/features/agent/SessionSettingsMenu";
import { DOCKABLE_PANEL_FRAME_CLASS, PANEL_HEADER_CLASS, useFloatingPanel } from "@/components/app/useFloatingPanel";
import { cn } from "@/lib/utils";
import type { ComposerChip } from "@/lib/composerChip";
import type { AgentMessageQuote } from "@/api/domains/sessions";

type AgentSession = components["schemas"]["AgentSessionOut"];
export type CanvasAgentMode = "docked" | "floating";
/**
 * 页面替用户投递的一条消息(笔记页选区工具条上的「润色」「翻译」……):面板接到就发,不经输入框。
 * `text` 是对话里显示的那句话,`context` 是这一条额外附给智能体的说明(接在页面上下文后面)。
 */
export type PageOutbox = { id: number; text: string; context: string };


/**
 * 工作区里的常驻智能体面板 —— 工作流、创意画板和剪辑页**共用这一个**。
 *
 * 它不是第二套 AI:会话池、消息、队列、确认卡走的都是同一套 agent session。各入口的差别
 * 只有三样东西 —— 给每条消息附加的隐藏上下文、空态那句话、输入框的例子。所以这里收参数,
 * 而不是各存一份六百行的副本:副本改一处只会改好其中一个,而两边看起来一模一样。
 */
/* 输入卡那一列的留边 —— 队列条共用这一个。侧栏很窄,差这 8px 一眼就看得出来。 */
const COMPOSER_COLUMN = "mx-2";

export function CanvasAgentChat({
  /** 附在每条消息上的隐藏上下文:告诉智能体它在看哪张画布、该用哪几个工具。
   *  给函数的话**发送那一刻**才取 —— 笔记页的正文和选区每敲一个字都在变,没必要为它每次重渲整页。 */
  contextLine,
  /** 页面挂进这条消息的东西(笔记页:选中的那段),和附件同一排小条。上下文由页面自己写进 contextLine。 */
  contextChips,
  /** 变一次就把光标放进输入框(笔记页的「问 AI」)。 */
  focusSignal,
  /** 这条消息带着的笔记摘录(笔记页的选区):落进消息,气泡里画成可点的一行,回看时也在。 */
  messageQuote,
  /** 页面投递的一条(见 PageOutbox):接到就发。**接走时先回调 onOutboxTaken**,页面清掉它 ——
   *  不清的话面板关了再开(重新挂载)会把同一条再发一遍。 */
  outbox,
  onOutboxTaken,
  /** 一条消息发出去了(输入框里的、页面投递的都算)。笔记页据此放下钉住的那段选区。 */
  onSent,
  /** 空态那句话 —— 说清这个面板能干什么。 */
  emptyHint,
  placeholder,
  /** 悬浮窗几何记忆的键。**各入口各记各的**:工作流、画板、剪辑页的大小位置互不干扰。 */
  rectKey,
  workspaceId,
  mode,
  dockedLayout = "overlay",
  onModeChange,
  onClose,
}: {
  contextLine: string | (() => string);
  contextChips?: ComposerChip[];
  focusSignal?: number;
  messageQuote?: AgentMessageQuote | null;
  outbox?: PageOutbox | null;
  onOutboxTaken?: () => void;
  onSent?: () => void;
  emptyHint: string;
  placeholder: string;
  rectKey: string;
  workspaceId: string;
  mode: CanvasAgentMode;
  /** Canvas docks cover content; the editor reserves a separate grid column. */
  dockedLayout?: "overlay" | "inline";
  /** 不给就没有「浮起来 / 停靠」那颗(ComfyUI 工作台的「助手」页签:就在那一列里)。 */
  onModeChange?: (mode: CanvasAgentMode) => void;
  /** 不给就没有关闭键(工作台的页签:换个页签就收起来了)。 */
  onClose?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  //: 草稿是**编辑器文档**,不是字符串 —— `@` 出来的引用是原子节点,存成字符串就散了。
  //: 要发出去的那句话由 `draftText` 从文档派生(引用序列化成 `@名字`)。
  const [draft, setDraft] = React.useState<JSONContent>(emptyDocument);
  const draftText = React.useMemo(() => documentText(draft), [draft]);
  const draftRefs = React.useMemo(() => collectReferences(draft), [draft]);
  const noteAttach = useNoteAttachments(workspaceId);
  // 多会话:和 AI 工作台、免提浮标、页面跳转共用同一个「当前会话」(见 currentAgentSession)——
  // 选择、新建、删后回落都在那里,这里不再各写一份。
  const current = useCurrentAgentSession(workspaceId, { pollList: 4000 });
  const sessionList = current.sessions;
  const activeSession = current.session;
  //: 同事共享来的对话**只能看**(判据在 currentAgentSession.isViewOnly):输入卡整张换成只读说明,
  //: 排队条和拍板的按钮也不给 —— 和 AI 工作台同一条。
  const readOnly = current.readOnly;
  //: 空串 = 还没有会话(各查询都以它为 enabled 条件)。
  const sessionId = activeSession?.id ?? "";
  // 连流 → 攒状态 → 收尾失效:**只有一份**,和 AI 工作台共用(见 useAgentTurnStream)。
  // 此前这里各写了一遍,而收尾那一步停在没修之前的写法 —— 每答完一句都会闪一下,
  // 而那个 bug 在隔壁文件里早就被诊断、注释、修好过。
  const { streamText, streamTimeline, attach: attachStream } = useAgentTurnStream(activeSession?.id ?? null);
  // 附件三种入口(选文件 / 拖放 / 粘贴)与对话页共用同一套逻辑,见 composerAttachments。
  const attach = useComposerAttachments(workspaceId);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const isFloating = mode === "floating";

  // 悬浮窗的拖动/缩放/位置记忆走共用 hook —— 执行历史面板用的是同一套。
  const { style: floatStyle, startDrag, handles, focusProps } = useFloatingPanel({
    storageKey: rectKey,
    floating: isFloating,
  });

  //: 贴底跟随(见 features/agent/stickToBottom)。此前这里是无条件 scrollTop = scrollHeight
  //: —— 用户往上翻历史会被每一次内容更新硬拽回底部。
  const stick = useStickToBottom<HTMLDivElement>(activeSession?.id);
  const newSession = current.create;
  const [deletingSession, setDeletingSession] = React.useState<AgentSession | null>(null);
  const deleteSession = useMutation({
    mutationFn: (id: string) => deleteAgentSession(id),
    onSuccess: (_data, deletedId) => {
      setDeletingSession(null);
      current.forget([deletedId]);
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
    },
  });

  const messages = useQuery({
    queryKey: ["agent-messages", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => listAgentMessages(sessionId),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });
  const sessionLoading = current.listPending || (Boolean(sessionId) && messages.isPending);
  /** 会话详情:运行状态、水位(列表接口不带 —— 那要为每个会话各算一次,而界面只看当前这个)。 */
  const live = useQuery({
    queryKey: ["agent-session", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => getAgentSession(sessionId),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });
  const running = live.data?.status === "running";
  //: 语音模式要念的三样东西。**用和子组件完全相同的 queryKey** —— react-query 按键共享缓存,
  //: 所以这里不会多发一次请求;另起一个键才会变成两套轮询。
  
  

  //: 语音只答**第一题**:一次念四道题再逐个记住答案,人是记不住的 —— 答完一题界面会把
  //: 下一题推上来,自然就轮到它。
  
  

  //: 最新一条助手回复的正文 —— 免提模式念的就是它。失败的那条不念(它的 content 是
  //: 「智能体执行失败」这类占位),但**失败要出声**由错误提示那条路负责,不是靠念它。
  
  //: 最近一条失败。**语音模式下必须出声** —— 静默的失败会被理解成"它没听见",
  //: 于是你再说一遍,然后再失败一次。
  
  // Same contract as the studio chat: a message typed mid-turn is a correction, the backend
  // injects it into the running turn, and one button covers stop-vs-send.
  // Same source of truth as the studio chat: the server knows what is still waiting.
  const queue = useQuery({
    queryKey: ["agent-queue", sessionId],
    enabled: Boolean(sessionId) && running,
    queryFn: () => listAgentQueue(sessionId),
    refetchInterval: 1500,
  });
  // 计费/用量:与对话页同源,按 agent_message_id 归到各条回复(见 MessageUsageFooter)。
  const usageEvents = useQuery({
    queryKey: ["agent-usage-events", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () => listAgentUsageEvents<AgentUsageEvent>(sessionId),
    refetchInterval: running ? 1200 : false,
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
  const queuedIds = new Set((running ? queue.data ?? [] : []).map((message) => message.id));

  // 和 ChatWorkspace 同一条规矩,同一个函数:答案已经被 `ask_user` 的工具结果记下的回执
  // 不再画一遍(见 features/agent/answerRecords)。两个面板各写一遍的话,这条迟早在其中
  // 一个上失效 —— 那正是「同一条流式协议两个面板各实现一遍」那个毛病的来路。
  const allMessages = messages.data ?? [];
  const recordedQuestions = React.useMemo(() => recordedQuestionIds(allMessages), [allMessages]);
  const visibleMessages = allMessages.filter((message) => !isRedundantAnswerRecord(message, recordedQuestions));
  //: 还没交给智能体的回执画在正在跑的那一轮**下面**:这一轮结束它才交出去(时间戳改成那一刻),
  //: 交出去之后它在对话里也排在这一轮的回答之后 —— 现在就按那个位置画,结束时不跳位。
  const transcript = visibleMessages.filter((message) => !isWaitingReceipt(message));
  const waitingReceipts = visibleMessages.filter(isWaitingReceipt);
  //: 对话里画出来的工具调用:对得上其中一行的确认卡就摆在那一行里,对不上的才退回列表末尾。
  const placedToolCalls = toolCallIds([
    ...visibleMessages.map((message) => (message.payload as { timeline?: AgentTimelineItem[] } | null)?.timeline),
    running ? streamTimeline : [],
  ]);
  //: 装着这段对话的那一块 —— 「有请求等你确认」在它里面找那张卡。
  const threadArea = React.useRef<HTMLDivElement | null>(null);

  /** 水位由会话详情**现算**给出,不从消息 payload 里翻。
   *  挂在消息上等于"必须先成功跑一轮才看得到" —— 而想知道"还能聊多久"的时刻恰恰在开口之前:
   *  刚打开旧会话、刚换过模型、上一轮失败了,这些时候都没有新的一轮可以带回这个数。 */
  const context = (live.data?.context ?? null) as ContextInfo | null;

  const compact = useMutation({
    mutationFn: () => compactAgentSession<{ compaction: CompactionInfo | null }>(sessionId),
    // 压成功了对话里会多一条整理记录;没得压和压失败必须说出来,否则只是 loading 闪一下。
    onSuccess: (result) => {
      void messages.refetch();
      void live.refetch();
      if (!result?.compaction) toast.message(t("agentCompactNothing"));
    },
    onError: (error) => toast.error(`${t("agentCompactFailed")}:${(error as Error).message}`),
  });
  const refreshQueue = () => {
    void qc.invalidateQueries({ queryKey: ["agent-queue", sessionId] });
    void qc.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
  };
  const cancelQueued = useMutation({
    mutationFn: (messageId: string) =>
      dropQueuedMessage(sessionId, messageId),
    onSuccess: refreshQueue,
  });
  const steerQueued = useMutation({
    mutationFn: (messageId: string) =>
      steerQueuedMessage(sessionId, messageId),
    onSuccess: (result) => {
      // 和工作台同一句:这一轮先结束了,消息留在队里自己跑 —— 不说的话,人以为已经插进了这一轮。
      if (!result.steered) toast.message(t("chatSteerTooLate"));
      refreshQueue();
    },
  });
  const showStop = running && !draftText.trim() && attach.isEmpty && !noteAttach.hasNotes;
  const stopTurn = useMutation({
    mutationFn: () => stopAgentSession(sessionId),
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


  React.useEffect(() => {
    if (running && sessionId) void attachStream(sessionId);
  }, [running, sessionId, attachStream]);

  const send = useMutation({
    mutationFn: async ({
      text,
      references,
      document,
      files,
      mediaAssets,
      quote,
      outboxContext,
    }: {
      text: string;
      references: AgentReference[];
      document: JSONContent | null;
      files: { name: string; content: string }[];
      mediaAssets: Asset[];
      quote: AgentMessageQuote | null;
      /** 页面投递的那一条(见 PageOutbox)带的说明。有它就说明这条不是输入框里的:输入框挂着的附件、笔记引用不跟着走。 */
      outboxContext?: string;
    }) => {
      const fromPage = outboxContext !== undefined;
      // 文本文件内联为围栏上下文(纯文本智能体可读);图片/视频/音频编码成附件标记,气泡里渲染成缩略图。
      const fileBlock = textAttachmentBlock(files, t("wfAgentAttached"));
      let visibleContent = text || files.map((file) => `[${t("wfAgentAttached")} ${file.name}]`).join("\n");
      for (const asset of mediaAssets) visibleContent += attachmentToken(asset);
      if (noteAttach.hasNotes && !fromPage) visibleContent += `\n${noteAttach.summary}`;
      visibleContent = visibleContent.trim();
      const page = typeof contextLine === "function" ? contextLine() : contextLine;
      const context = [page, outboxContext, fileBlock, fromPage ? "" : noteAttach.context].filter(Boolean).join("\n\n");
      //: 先在这里说,不等后端回一句英文的「at most 4000 characters」(见 composerAttachments 的 MAX_*_CHARS)。
      if (visibleContent.length > MAX_MESSAGE_CHARS || context.length > MAX_CONTEXT_CHARS) {
        throw new Error(t("composerMessageTooLong"));
      }
      const targetId = (await current.ensure()).id;
      //: 「/」点名的技能(ADR 0040 §4):全文由后端挂到这一轮。
      const skills = document ? collectSkills(document) : [];
      const message = await sendAgentMessage(targetId, {
        content: visibleContent, context, references, ...(document ? { body_document: document } : {}), ...(quote ? { quote } : {}),
        ...(skills.length ? { skills } : {}),
      });
      return { message, targetId, fromPage };
    },
    onError: (error) => toast.error((error as Error).message),
    onSuccess: ({ targetId, fromPage }) => {
      //: 页面投递的那条不经输入框:输入框里正写着的草稿、挂着的附件都不是它的,不动。
      if (!fromPage) {
        setDraft(emptyDocument);
        noteAttach.clear();
        attach.clear();
      }
      onSent?.();
      void qc.invalidateQueries({ queryKey: ["agent-queue", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-messages", targetId] });
      void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
      void attachStream(targetId);
    },
  });

  //: 页面投递的一条:接到就发(只读的会话发不了,说一声)。依赖只看 id —— 同一条不发第二遍。
  React.useEffect(() => {
    if (!outbox) return;
    onOutboxTaken?.();
    if (readOnly) {
      toast.message(t("chatSessionReadOnly"));
      return;
    }
    send.mutate({
      text: outbox.text, references: [], document: null, files: [], mediaAssets: [],
      quote: messageQuote ?? null, outboxContext: outbox.context,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outbox?.id]);

  const submit = () => {
    // `running` is deliberately not a guard: the backend steers a mid-turn message.
    if ((!draftText.trim() && attach.isEmpty && !noteAttach.hasNotes) || send.isPending) return;
    send.mutate({
      text: draftText.trim(),
      references: draftRefs,
      document: draft,
      files: attach.files,
      mediaAssets: attach.media,
      quote: messageQuote ?? null,
    });
  };

  return (
    <aside
      className={cn(
        // 行方向锁了,列方向也得锁:这个 grid 没声明 grid-template-columns,隐式列按 auto
        // (= max-content)定尺 —— 标题栏那个 nowrap 的会话名会把整列撑到内容宽度。于是
        // h2 的 truncate 永远不触发(它根本没被压缩过),省略号出不来;右端新建/停靠/关闭
        // 三个按钮被推出面板,最后由外框的 overflow-hidden 一刀切掉。停靠态看着是「正文被
        // 硬裁」,悬浮态看着是「窗口被内容撑宽」—— 同一个成因的两种样子。
        "grid grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto]",
        !isFloating && dockedLayout === "inline"
          ? "overflow-hidden bg-workspace-panel"
          : DOCKABLE_PANEL_FRAME_CLASS,
        isFloating
          ? "fixed min-h-[380px] min-w-[320px] max-h-[calc(100vh-24px)] max-w-[calc(100vw-24px)] border-floating-border"
          // **停靠不等于没有影子。** 停靠成右栏时它仍然浮在画布之上(整条右栏是 absolute),
          // 和执行历史面板并排 —— 而那一个是有影子的。此前这里无条件 shadow-none,于是同一条
          // 右栏里上下两块,一块浮着一块贴着。inline 停靠(3D 场景页)本来就走上面那条分支,
          // 拿的是 bg-workspace-panel、根本没有影子类,不需要在这儿再抹一次。
          : "relative z-[1] h-full w-full min-h-0 min-w-0",
      )}
      style={floatStyle}
      {...focusProps}
      role={isFloating ? "dialog" : "complementary"}
      aria-label={t("wfAgentTitle")}
      //: 文件拖到整个面板上都算数,不只是输入卡;只读时没有输入卡,也就不接(和 AI 工作台同一条)。
      //: 覆盖层靠这个 aside 定位:停靠时它是 relative,悬浮时是 fixed。
      {...(readOnly ? {} : attach.drop.handlers)}
    >
      {handles}
      {!readOnly && attach.drop.overlay}
      {/* 确认卡跟着对话走:取卡、拍板在这一层,对话里每一次工具调用的那一行各自查自己的卡(见 PendingDecisions)。 */}
      <SessionDecisions workspaceId={workspaceId} sessionId={activeSession?.id ?? null} readOnly={readOnly} live={running}>
      <div className={cn(PANEL_HEADER_CLASS, isFloating && "cursor-move")} onPointerDown={startDrag}>
        {/* h2 会吃满按钮以外的剩余标题栏，悬浮时这整段都是拖动命中区。会话标题本身仍是
            button，useFloatingPanel 会排除它，所以单击切会话与拖窗口不会互相抢事件。此前把
            data-no-drag 挂在整个 h2 上，等于把标题栏唯一的大块空白也一起禁用了。 */}
        <h2 className="min-w-0 overflow-hidden pr-6">
          <AgentSessionSwitcher
            sessions={sessionList}
            activeSession={activeSession}
            deleting={deleteSession.isPending}
            onSelect={current.select}
            onDelete={setDeletingSession}
          />
        </h2>
        <IconButton
          unstyled
          type="button"
          className="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
          label={t("wfAgentNewSession")}
          loading={newSession.isPending}
          onClick={() => newSession.mutate()}
        >
          <Plus size={13} />
        </IconButton>
        {onModeChange && (
          <IconButton
            unstyled
            type="button"
            className="ml-auto grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
            label={isFloating ? t("wfAgentDock") : t("wfAgentFloat")}
            onClick={() => onModeChange(isFloating ? "docked" : "floating")}
          >
            {isFloating ? <PanelRight size={13} /> : <Move size={13} />}
          </IconButton>
        )}
        {onClose && (
          <IconButton unstyled type="button" className="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive" label={t("close")} onClick={onClose}>
            <X size={13} />
          </IconButton>
        )}
      </div>
      <div className="relative grid min-h-0 min-w-0" ref={threadArea}>
      <div
        className={cn(
          // 横向必须一起锁死。grid 子项默认 min-width:auto —— 一段长代码块 / 一条长 URL 会把
          // 整列撑宽,于是整个助手面板可以左右滚,正文跟着晃。grid-cols 显式给 minmax(0,1fr)
          // 才让子项允许被压缩,overflow-x-hidden 兜住越界的那一点。
          // (代码块自己有 overflow-x-auto,但那只在父容器被约束时才生效。)
          "grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-y-auto overflow-x-hidden p-2.5",
          (sessionLoading || (messages.data ?? []).length === 0) && !running && "content-center justify-items-center",
        )}
        ref={stick.ref}
      >
        {/* 「还没读到」不能说成「是空的」—— 和工作台同一条规矩:读取中闪出的空态提示在说这条会话是空的。 */}
        {sessionLoading && !running && <LoadingState label={t("chatLoadingSession")} />}
        {!sessionLoading && (messages.data ?? []).length === 0 && !running && (
          <div className="grid justify-items-center gap-1.5 p-2.5 text-center text-xs text-muted-foreground [&_svg]:text-primary [&_svg]:opacity-70">
            <Bot size={16} />
            <span>{emptyHint}</span>
          </div>
        )}
        {transcript.map((message) => {
          const payload = message.payload as
            | {
                usage?: { duration_seconds?: number };
                timeline?: AgentTimelineItem[];
                compaction?: CompactionInfo;
                /** 用户消息:编辑器原样的文档,气泡照它把引用画回胶囊。 */
                body_document?: JSONContent;
                /** 用户消息:这条是一次**选择的回执**,问的什么、选的哪一项都在里面。 */
                answers?: AnsweredChoice;
                /** 用户消息:带着的笔记摘录(笔记页的选区)。 */
                quote?: AgentMessageQuote;
              }
            | null;
          const duration = payload?.usage?.duration_seconds;
          if (queuedIds.has(message.id)) return null;
          // 手动压缩留下的是一条 role=system、内容为空的消息:它只承载压缩标记。
          if (message.role === "system") {
            return payload?.compaction ? <CompactionNotice key={message.id} info={payload.compaction} /> : null;
          }
          // 后台任务的回执:一行任务通知,不是用户气泡(见 JobReceiptNotice)。
          if (message.role === JOB_RECEIPT_ROLE) {
            return <JobReceiptNotice key={message.id} content={message.content} payload={message.payload} />;
          }
          return (
            <div
              key={message.id}
              className={
                message.role === "assistant"
                  ? "relative w-full min-w-0 max-w-full text-ui-md leading-[1.65] [word-break:break-word]"
                  : "ml-auto mr-0 w-fit min-w-0 max-w-[min(560px,88%)] justify-self-end whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]"
              }
            >
              {message.role === "assistant" && payload?.compaction && (
                <div className="mb-1.5">
                  <CompactionNotice info={payload.compaction} />
                </div>
              )}
              {message.role === "assistant" ? (
                /* 和 ChatBubble 同一条:过程在上、失败原因在下,而不是二选一。 */
                <>
                  <AgentTurnContent timeline={payload?.timeline} />
                  {message.error && (
                    <div className={payload?.timeline?.length ? "mt-2" : undefined}>
                      <AgentErrorCard content={message.content} error={message.error} />
                    </div>
                  )}
                </>
              ) : (
                payload?.answers ? (
                  <AnsweredChoiceCard answers={payload.answers} />
                ) : (
                  <UserMessageContent content={message.content} document={payload?.body_document} quote={payload?.quote} />
                )
              )}
              {message.role === "assistant" && (
                <MessageUsageFooter
                  messageId={message.id}
                  workspaceId={workspaceId}
                  content={message.content}
                  usageEvents={usageByMessage.get(message.id) ?? []}
                  durationOverride={duration}
                  className="flex-wrap text-muted-foreground"
                />
              )}
            </div>
          );
        })}
        {running && streamText && (
          <div className="relative w-full min-w-0 max-w-full text-ui-md leading-[1.65] [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <AgentStatusRow className="mt-1.5" meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))} />
          </div>
        )}
        {running && !streamText && (
          <div className="relative flex w-full min-w-0 max-w-full flex-col items-stretch gap-1.5 text-ui-md leading-[1.65] text-muted-foreground [word-break:break-word]">
            <AgentTurnContent timeline={streamTimeline} />
            <AgentStatusRow label={t("chatThinking")} meta={t("usageRunning").replace("{t}", formatElapsedSeconds(elapsedSeconds))} />
          </div>
        )}
        <PendingDecisions placed={placedToolCalls} />
        {waitingReceipts.map((message) => (
          <JobReceiptNotice key={message.id} content={message.content} payload={message.payload} />
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
      {readOnly ? (
        <p
          role="note"
          className={cn(COMPOSER_COLUMN, "mb-2 mt-2 flex items-start gap-2 rounded-lg border border-dashed border-border px-2.5 py-2 text-ui-sm leading-[1.55] text-muted-foreground")}
        >
          <Eye size={14} className="mt-[3px] shrink-0" aria-hidden />
          {t("chatSessionReadOnly")}
        </p>
      ) : (
        <>
          <QueuedMessages
            messages={queue.data ?? []}
            /* 和下面那张输入卡同样的留边(mx-2)—— 侧栏很窄,差这 8px 一眼就看得出来。 */
            className={COMPOSER_COLUMN}
            onSteer={(id) => steerQueued.mutate(id)}
            onCancel={(id) => cancelQueued.mutate(id)}
            steering={steerQueued.isPending}
            cancelling={cancelQueued.isPending}
          />
          <div className={cn(COMPOSER_COLUMN, "mb-2 mt-2 flex flex-col gap-0.5 rounded-lg border border-border bg-control px-2 pb-1.5 pt-2 transition-[border-color] duration-100 focus-within:border-ring")}>
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                void attach.accept(event.target.files);
                event.target.value = "";
              }}
            />
            {/* 内层去底色/边框/焦点环:外层输入卡已是表面,双层盒子叠着难看(对话页同款处理)。 */}
            {/* 附件和笔记引用是同一件事:这条消息里带了什么。一排,在输入卡里。 */}
            <ComposerChips chips={[...(contextChips ?? []), ...attach.chips, ...noteAttach.chips]} uploading={attach.uploading} />
            {attach.previewModal}
            {noteAttach.dialog}
            {/* `@` 唤起素材 / 笔记 / 画板 / 工作流的引用。引用是原子节点,不是一段可以被删掉半个的字。 */}
            <ChatComposer
              workspaceId={workspaceId}
              value={draft}
              onChange={setDraft}
              onSubmit={() => submit()}
              onPaste={attach.onPaste}
              placeholder={placeholder}
              focusSignal={focusSignal}
            />
            <div className="flex items-center justify-between gap-1.5">
              <div className="flex min-w-0 items-center gap-1">
                {noteAttach.trigger}
                {/* icon-xs(28px)是工具栏那一档,整行统一走它。默认的 icon 是 36px,
                    在这一行里会比旁边的胶囊高出一截 —— 圆形按钮尤其藏不住这 8px。 */}
                <IconButton
                  variant="ghost"
                  size="icon-xs"
                  label={t("wfAgentAttach")}
                  onClick={() => fileRef.current?.click()}
                >
                  <Paperclip size={14} />
                </IconButton>
                {/* 说话输入紧挨着附件:两者都是"往输入框里放东西",而模型选择是"怎么处理它"。 */}
                <DictateButton
                  onText={(text) =>
                    // **追加**,不覆盖 —— 他可能先打了半句再改用说的。
                    setDraft((current) => appendText(current, text))
                  }
                />
                {/* 免提是另一件事:说话输入把话填进框里等你过目,这个直接发出去。做成一个按钮的
                    两种模式的话,每次都要先想清楚自己现在处在哪一种,而两者的后果差得很远。 */}
                {/* 免提不在这一行:它是"手离开键盘"的模式,而工具行只在助手面板打开时才在屏幕上 ——
                    恰好在最需要它的时候不见了。改成应用级的浮标(features/agent/VoiceDock),
                    由设置里的开关决定浮不浮。说话输入留着:那个是"把话填进这个框",本来就属于这里。 */}
                {/* 会话详情还在读时先用清单里那份:两者是同一条会话,只差水位。 */}
                <ModelPicker workspaceId={workspaceId} session={live.data ?? activeSession} />
                {/* 与 AI Studio 用同一个组件:此前两边各写各的工具行,同一个功能的位置、顺序、
                    有无都不一致。 */}
                <SessionSettingsMenu
                  workspaceId={workspaceId}
                  session={live.data ?? activeSession}
                  context={context}
                  compacting={compact.isPending}
                  onCompact={running ? undefined : () => compact.mutate()}
                />
              </div>
              {showStop ? (
                <IconButton
                  variant="default"
                  size="icon"
                  className="rounded-full"
                  label={t("chatStop")}
                  loading={stopTurn.isPending}
                  onClick={() => stopTurn.mutate()}
                >
                  <Square size={12} fill="currentColor" />
                </IconButton>
              ) : (
                <IconButton
                  variant="default"
                  size="icon"
                  className="rounded-full"
                  label={running ? t("chatSteer") : t("chatSend")}
                  hint={running ? t("chatSteerHint") : undefined}
                  disabled={(!draftText.trim() && attach.isEmpty && !noteAttach.hasNotes) || attach.uploading} loading={send.isPending}
                  disabledReason={attach.uploading ? t("composerUploading") : undefined}
                  onClick={submit}
                >
                  <Send size={14} />
                </IconButton>
              )}
            </div>
          </div>
        </>
      )}
      </SessionDecisions>
      <ConfirmDialog
        open={deletingSession !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteSessionBody")}
        onCancel={() => setDeletingSession(null)}
        pending={deleteSession.isPending}
        onConfirm={() => deletingSession && deleteSession.mutate(deletingSession.id)}
      />
    </aside>
  );
}
