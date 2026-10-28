import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { CornerUpLeft, Eye, FolderInput, FolderPlus, ListChecks, MessageSquarePlus, Pencil, Plus, Search, SearchX, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createSessionGroup,
  deleteSessionGroup,
  listSessionGroups,
  renameSessionGroup,
  type SessionGroup,
  type SessionGroupKind,
} from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { WriteBlock } from "@/components/layout/useWriteBlocked";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { GroupToggle } from "@/components/ui/group-toggle";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { IconButton } from "@/components/ui/icon-button";
import { Marker, MarkerContent } from "@/components/ui/marker";
import { MenuItemBody } from "@/components/ui/menu";
import { Skeleton, SkeletonLine } from "@/components/ui/skeleton";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { SessionShareMenuItem } from "@/features/ai-studio/SessionShareMenuItem";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { cn } from "@/lib/utils";
import { useDndAccessibility } from "@/components/app/dndAccessibility";

/**
 * 行上多说的一句和多出的一颗按钮(对话列表:「在剪辑《A》里开的」和「回到那里」,ADR 0044 §5)。生成会话没有,不给。
 * 由调用方说 —— 列表本身不认识「家」这回事,和它不认识两种会话的差异是同一个道理(见 SESSION_KINDS)。
 */
export interface SessionRowExtras {
  subtitle?: string;
  /**
   * 「回到那里」:点了就去那一处开出来那条。
   *
   * 去 ComfyUI 工作台要好几步(读那台机器的工作流库、探/起它背后的本机服务、亮出视图、把那一张读进画布),几秒到一两分钟
   * 都有;这一行自己把这段说出来:箭头转圈、名字换成「正在启动…」,转完(成败都算)恢复原样。真要去起本机服务时,那一处叫一声
   * `onStarting` —— 这一行再把说明换成「第一次启动可能要一两分钟」(见 goToPlace 的 `onStarting`)。
   *
   * 失败由给这一颗的人说话(它知道那一处该怎么讲,见调用处的 `.catch(toast.error)`);这一行只保证圈一定收掉。
   */
  goBack?: { label: string; hint: string; onClick: (onStarting: () => void) => void | Promise<unknown> };
  /** 标题后面的小标(创作会话:这是哪一种 —— 图像、语音、播客……,ADR 0055)。 */
  badge?: React.ReactNode;
}

/** 这个列表认得的会话:两种会话都有这三样,别的它不碰。 */
export interface ListedSession {
  id: string;
  title: string;
  group_id?: string | null;
  //  分享菜单要看这两个(SessionShareMenuItem):是不是我的、有没有分享出去。
  is_mine: boolean;
  shared: boolean;
}

/**
 * 两种会话的差异**全在这里**,组件里没有一处 if (kind === ...)。
 *
 * 差的只是「打哪个地址」「缓存键叫什么」「分享时算哪一类」—— 列表怎么组织、怎么拖、
 * 怎么批量删,两边一模一样。把差异摊成一张表而不是分支,是因为下次再来第三种会话时,
 * 该改的地方只有这张表;写成分支的话,得把整个组件重读一遍找齐所有分叉。
 */
interface SessionKindSpec {
  sessionsQueryKey: string;
  path: (id: string) => string;
  shareKind: "agent_session" | "generation_session";
  title: MessageKey;
  newSession: MessageKey;
  empty: MessageKey;
  /**
   * 列表还在读时给读屏念的那一句(见 SessionListSkeleton)。两种会话说的不是同一样东西 ——
   * 「读取对话…」/「读取创作会话…」,所以它和 `empty` 一样落在这一张表里。
   */
  loading: MessageKey;
  searchPlaceholder: MessageKey;
  searchNoMatch: MessageKey;
  renameTitle: MessageKey;
  deleteBody: MessageKey;
  deleteGroupBody: MessageKey;
  /** 批量删。措辞里带数量和「会一并删掉什么」—— 两种会话删掉的东西不一样。 */
  deleteManyBody: MessageKey;
  /**
   * 同事共享来的会话**只能看**,那一行说什么(不给改名、删除、收纳、拖动;批量选不中它)。两种会话同一条规矩
   * (后端 domain/sharing 的写闸:只有主人能写),差的只是这句话。
   */
  sharedIsViewOnly: MessageKey;
}

const SESSION_KINDS: Record<SessionGroupKind, SessionKindSpec> = {
  agent: {
    sessionsQueryKey: "agent-sessions",
    path: (id: string) => `/api/agent/sessions/${id}`,
    shareKind: "agent_session" as const,
    title: "chatSessionsTitle",
    newSession: "chatNewSession",
    empty: "chatNoSessions",
    loading: "chatSessionsLoading",
    searchPlaceholder: "chatSearchSessions",
    searchNoMatch: "chatSearchNoMatch",
    renameTitle: "renameSession",
    deleteBody: "deleteSessionBody",
    deleteGroupBody: "chatDeleteGroupBody",
    deleteManyBody: "chatDeleteSessionsBody",
    sharedIsViewOnly: "chatSessionReadOnly",
  },
  generation: {
    sessionsQueryKey: "generation-sessions",
    path: (id: string) => `/api/generation/sessions/${id}`,
    shareKind: "generation_session" as const,
    title: "generationSessionsTitle",
    newSession: "generationNewSession",
    empty: "generationNoSessions",
    loading: "generationSessionsLoading",
    searchPlaceholder: "generationSearchSessions",
    searchNoMatch: "generationSearchNoMatch",
    renameTitle: "renameGenerationSession",
    deleteBody: "deleteGenerationSessionBody",
    deleteGroupBody: "generationDeleteGroupBody",
    deleteManyBody: "generationDeleteSessionsBody",
    sharedIsViewOnly: "generationSessionReadOnly",
  },
};

/** 这个人能管的那几条:自己的。共享来只能看的不进多选(批量删一定会被拒,摆出来只是让他白点一次)。 */
function manageable(session: ListedSession): boolean {
  return session.is_mine;
}

/** 收进分组;`null` = 移出分组(接口用空串表达"改成没有")。 */
function moveSessionToGroup(kind: SessionGroupKind, sessionId: string, groupId: string | null): Promise<unknown> {
  return api(SESSION_KINDS[kind].path(sessionId), {
    method: "PATCH",
    body: JSON.stringify({ group_id: groupId ?? "" }),
  });
}

/**
 * 一行的**壳**:那一圈内边距 + 标题/副标题那一列。真行(见 SessionRow 的 rowButton)和加载中的
 * 骨架行共用这一串 —— 各写一份的话,哪天改了内边距,加载完列表就会整体挪一下(见 SessionListSkeleton)。
 */
const SESSION_ROW_BODY =
  "grid w-full grid-cols-[minmax(0,1fr)] items-center gap-px border-0 bg-transparent px-3 py-3 text-left";

/** 一屏大概放得下的行数。它说的是「正在来」,不是「有 6 条」—— 真有几条此刻还不知道。 */
const SESSION_SKELETON_ROWS = 6;

/** 标题长短不一。一样宽的一列灰条看着像一张表格,不像一份会话清单。 */
const SESSION_SKELETON_WIDTHS = ["62%", "44%", "78%", "35%", "55%", "70%"];

/**
 * 会话列表**还没读回来**时的样子。
 *
 * 维护者报的:AI Studio 左边的「对话记录」在智能体读回来之前**看着是空的** —— 上面还先闪出一排
 * 「素材调研 0 / 素材生成 0」的分组,像是这个工作区一条都没有。其实是还没到。
 *
 * 所以这几行照**真行**的版式铺(同一个 SESSION_ROW_BODY、同样那两行字),分组标题那一块也占着
 * (照 GroupToggle 的排版,但它是块死占位:不是按钮、不转、不悬停变色,免得看着像能点)。
 * 空态那两句(chatNoSessions / generationNoSessions)只留给**确实没有**,搜索无果那条路也不铺骨架。
 *
 * 读屏那边:一个 `role="status"` + `aria-busy` 的状态区,里面只有一句 sr-only 的话;那些假行
 * 各自 `aria-hidden` —— 一屏灰条不该被念成「这里有六条对话」(既有约定见 AssetGridPicker 的 GridSkeleton)。
 */
function SessionListSkeleton({ label, rows = SESSION_SKELETON_ROWS }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-busy="true" data-session-skeleton="" className="grid content-start gap-1">
      <span className="sr-only">{label}</span>
      <div
        aria-hidden="true"
        data-session-skeleton-group=""
        className="flex w-full items-center gap-1 px-1.5 py-1 text-left text-ui-xs font-medium"
      >
        <Skeleton className="size-3 shrink-0 rounded-sm" />
        <span className="flex-1">
          <SkeletonLine className="w-[72px]" />
        </span>
        <Skeleton className="h-2.5 w-3 shrink-0" />
      </div>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} aria-hidden="true" data-session-skeleton-row="" className={SESSION_ROW_BODY}>
          <span className="grid min-w-0 gap-0.5">
            {/* 字号落在**外层**这一格上:两行字的高度由它定(`lh` 相对这一层的行高)。 */}
            <span className="text-ui-sm">
              <SkeletonLine className={SESSION_SKELETON_WIDTHS[index % SESSION_SKELETON_WIDTHS.length]} />
            </span>
            {/* 真列表里不是每行都有副标题(家就在这一处的对话没有「在别处开的」那句):骨架也长短不一,
                整屏都是两行的话,加载完会看着矮一截。 */}
            {index % 3 !== 2 && (
              <span className="text-ui-xs">
                <SkeletonLine className="w-[38%]" />
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * 左侧的对话列表:分组收纳 + 批量删除。
 *
 * 从 ChatWorkspace 抽出来 —— 那个文件已经一千多行,而"列表怎么组织"和"这一轮怎么跑"
 * 是两件互不相干的事。列表自己管改名/删除/分组的弹窗与请求,对外只报「选了哪个」「删掉了谁」。
 *
 * 多选走 lib/useMultiSelect(素材、发布、工作流三处同一份),批量删除也照它们的做法逐条删、
 * 失败的报出来 —— 后端没有批量接口,而逐条删至少让"删了 8 个失败 2 个"说得出口。
 */
export function SessionList<S extends ListedSession>({
  kind,
  workspaceId,
  sessions,
  loaded,
  loading = false,
  activeSessionId,
  onSelect,
  onCreate,
  creating,
  onDeleted,
  extras,
  toolbar,
  emptyTitle,
  aside,
  writeBlocked = null,
}: {
  /** 对话还是生成 —— 两边各自一套分组,差异全在 SESSION_KINDS 那张表里。 */
  kind: SessionGroupKind;
  workspaceId: string;
  sessions: S[];
  loaded: boolean;
  /**
   * 这一列还在从服务端读。调用方给的是那条查询的 `isPending`(`isPending` 只在**一条都还没读到**时为真,
   * 所以轮询的每一次重取不会把列表换成骨架)。
   *
   * 「还没读到」和「确实没有」是两回事:前者铺骨架(见 SessionListSkeleton),后者的空态
   * (chatNoSessions / generationNoSessions)只留给后者。没给 = 不铺。
   */
  loading?: boolean;
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  creating: boolean;
  /** 删掉了这些会话 —— 当前打开的那个若在其中,调用方要把它从视图里放下。 */
  onDeleted: (ids: string[]) => void;
  /** 行上多说的一句、多出的一颗按钮(见 SessionRowExtras)。 */
  extras?: (session: S) => SessionRowExtras | null;
  /** 标题行下面、搜索框上面的那一排(创作页的种类筛选)。 */
  toolbar?: React.ReactNode;
  /** 一条都没有时说什么。没给就是这一类会话的那句(SESSION_KINDS);创作页按筛选的种类说。 */
  emptyTitle?: string;
  /**
   * 收在列表最下面、默认合着的那一摞(创作页的「来自别处」:画板、工作流、智能体……那里开出来的会话,ADR 0052)。
   * 只收**没进分组**的:用户亲手收进分组的,照旧在那个分组里。搜索时它照样参与,有命中就展开着。
   */
  aside?: { title: string; isAside: (session: S) => boolean };
  /** 只读成员:新建会话、新建分组、分组改名和删除收成灰的,说明为什么(见 useWriteBlocked)。 */
  writeBlocked?: WriteBlock | null;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const spec = SESSION_KINDS[kind];
  const [renamingSession, setRenamingSession] = React.useState<ListedSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<ListedSession | null>(null);
  const [renamingGroup, setRenamingGroup] = React.useState<SessionGroup | null>(null);
  const [deletingGroup, setDeletingGroup] = React.useState<SessionGroup | null>(null);
  const [creatingGroup, setCreatingGroup] = React.useState(false);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const [query, setQuery] = React.useState("");
  // 折叠状态只活在这次会话里:它是"我现在不想看这一摞",不是设置。
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());
  //: 「来自别处」默认合着:这一屏是这里开的那些(ADR 0052 §3)
  const [asideOpen, setAsideOpen] = React.useState(false);

  const groups = useQuery({
    queryKey: ["session-groups", kind, workspaceId],
    queryFn: () => listSessionGroups(workspaceId, kind),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: [spec.sessionsQueryKey, workspaceId] });
    void qc.invalidateQueries({ queryKey: ["session-groups", kind, workspaceId] });
  };

  const manageableSessions = React.useMemo(() => sessions.filter(manageable), [sessions]);
  const { selectMode, enter: enterSelectMode, selectedIds, toggle, selectAll, allSelected, exit } = useMultiSelect(
    manageableSessions,
    (session) => session.id,
  );

  const renameSession = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api(spec.path(id), { method: "PATCH", body: JSON.stringify({ title: name }) }),
    onSuccess: () => {
      setRenamingSession(null);
      refresh();
    },
  });
  const removeSession = useMutation({
    mutationFn: (id: string) => api(spec.path(id), { method: "DELETE" }),
    onSuccess: (_data, id) => {
      setDeletingSession(null);
      onDeleted([id]);
      refresh();
    },
  });
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 没有批量接口:逐条删,失败的报出去(和素材页/工作流页同一种做法)。
      const ids = [...selectedIds];
      const removed: string[] = [];
      const failures: string[] = [];
      for (const id of ids) {
        try {
          await api(spec.path(id), { method: "DELETE" });
          removed.push(id);
        } catch (error) {
          failures.push(String((error as Error).message));
        }
      }
      return { removed, failures };
    },
    onSuccess: ({ removed, failures }) => {
      setBatchDeleting(false);
      exit();
      onDeleted(removed);
      refresh();
      if (failures.length > 0) toast.error(failures[0]);
    },
  });
  const addGroup = useMutation({
    mutationFn: (name: string) => createSessionGroup(workspaceId, kind, name),
    onSuccess: () => {
      setCreatingGroup(false);
      refresh();
    },
  });
  const editGroup = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameSessionGroup(id, name),
    onSuccess: () => {
      setRenamingGroup(null);
      refresh();
    },
  });
  const removeGroup = useMutation({
    mutationFn: (id: string) => deleteSessionGroup(id),
    onSuccess: () => {
      setDeletingGroup(null);
      refresh();
    },
  });
  const moveSession = useMutation({
    mutationFn: ({ id, groupId }: { id: string; groupId: string | null }) => moveSessionToGroup(kind, id, groupId),
    onSuccess: refresh,
  });

  const groupList = groups.data ?? [];
  // 按标题筛。搜索时**不改变分组结构**,只是把不匹配的行拿掉、空掉的分组整段收起 ——
  // 拍平成一列会让人分不清找到的这条本来收在哪儿。
  const keyword = query.trim().toLowerCase();
  const visible = React.useMemo(
    () => (keyword ? sessions.filter((session) => session.title.toLowerCase().includes(keyword)) : sessions),
    [sessions, keyword],
  );
  const visibleManageable = React.useMemo(() => visible.filter(manageable), [visible]);
  // 分组内 / 未分组两摞。会话本身的顺序(后端按 updated_at 倒序)在每一摞里保持不变。
  const byGroup = React.useMemo(() => {
    const map = new Map<string, S[]>();
    const loose: S[] = [];
    for (const session of visible) {
      const groupId = session.group_id;
      if (groupId && groupList.some((group) => group.id === groupId)) {
        map.set(groupId, [...(map.get(groupId) ?? []), session]);
      } else {
        loose.push(session);
      }
    }
    //: 没进分组的再分两摞:这里开的,和收在最下面的「来自别处」
    const isAside = aside?.isAside;
    return {
      map,
      loose,
      main: isAside ? loose.filter((session) => !isAside(session)) : loose,
      aside: isAside ? loose.filter((session) => isAside(session)) : [],
    };
  }, [visible, groupList, aside?.isAside]);
  //: 这里开的一条都没有(「来自别处」那摞不算):空态照说
  const mainCount = aside ? sessions.filter((session) => !aside.isAside(session)).length : sessions.length;
  //: 铺骨架:**还没读到任何一条**的时候。读到过的照旧摆着 —— 轮询重取(对话那一列每 4 秒一次)不该把列表换成骨架。
  const showSkeleton = loading && sessions.length === 0;
  const asideShown = asideOpen || Boolean(keyword);
  //: 开着的那条在「来自别处」里(从任务中心、「在哪里用过」、「回到」带过来的):展开,看得见它在哪一行;之后照样能合上
  const activeInAside = Boolean(activeSessionId) && byGroup.aside.some((session) => session.id === activeSessionId);
  React.useEffect(() => {
    if (activeInAside) setAsideOpen(true);
  }, [activeInAside, activeSessionId]);

  // 未分组那一摞的容器键。用一个不可能撞上 id 的常量,免得和真实分组 id 混在一起。
  const UNGROUPED = "__ungrouped__";
  const containers = React.useMemo(() => {
    const map: Record<string, string[]> = { [UNGROUPED]: byGroup.loose.map((session) => session.id) };
    for (const group of groupList) map[group.id] = (byGroup.map.get(group.id) ?? []).map((session) => session.id);
    return map;
  }, [byGroup, groupList]);

  const [draggingId, setDraggingId] = React.useState<string | null>(null);
  // 6px 起手:和剪辑页拖素材同一套 —— 不吃普通点击,也不吃右键菜单。
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const dndAccessibility = useDndAccessibility();

  const containerOf = (id: string) =>
    Object.keys(containers).find((key) => containers[key].includes(id)) ?? UNGROUPED;

  const onDragEnd = (event: DragEndEvent) => {
    setDraggingId(null);
    const activeId = String(event.active.id);
    const over = event.over;
    if (!over) return;
    const overId = String(over.id);
    // 拖拽只做一件事:换分组。落在分组标题上进那个分组,落在别的对话上进它所在的分组。
    // 组内先后由「最近更新」决定,不接受手排 —— 见下面 containers 的说明。
    const to = overId.startsWith("group:") ? overId.slice("group:".length) : containerOf(overId);
    if (containerOf(activeId) === to) return;

    const groupId = to === UNGROUPED ? null : to;
    // 先把界面摆好再落库:等一个来回的话,松手那一刻会看到它弹回原位。按前缀改 —— 生成会话的列表键
    // 后面还跟着是哪一页(见 GenerateWorkspace),精确的键对不上。
    qc.setQueriesData<ListedSession[]>({ queryKey: [spec.sessionsQueryKey, workspaceId] }, (old) =>
      old?.map((session) => (session.id === activeId ? { ...session, group_id: groupId } : session)),
    );
    moveSession.mutate({ id: activeId, groupId });
  };

  const renderSession = (session: S) => (
    <SessionRow
      key={session.id}
      kind={kind}
      session={session}
      extras={extras?.(session) ?? null}
      viewOnly={manageable(session) ? undefined : spec.sharedIsViewOnly}
      groups={groupList}
      active={!selectMode && activeSessionId === session.id}
      selectMode={selectMode}
      checked={selectedIds.has(session.id)}
      dragging={draggingId === session.id}
      workspaceId={workspaceId}
      onOpen={() => {
        if (!selectMode) onSelect(session.id);
        else if (manageable(session)) toggle(session.id);
      }}
      onRename={() => setRenamingSession(session)}
      onDelete={() => setDeletingSession(session)}
      onMove={(groupId) => moveSession.mutate({ id: session.id, groupId })}
      onNewGroup={() => setCreatingGroup(true)}
    />
  );

  return (
    <>
      <div className="flex min-h-14 shrink-0 items-center justify-between gap-1 border-b border-divider px-3 [&_h2]:m-0 [&_h2]:text-ui-md [&_h2]:font-semibold [&_h2]:text-foreground">
        {selectMode ? (
          // 选择模式下头部换成这一批的动作 —— 和素材/工作流/发布三页同一套语汇。
          <>
            <h2>{t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}</h2>
            <span className="flex items-center gap-0.5">
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={allSelected(visibleManageable) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                onClick={() => selectAll(visibleManageable)}
              >
                <ListChecks size={14} />
              </IconButton>
              <IconButton
                variant="ghost"
                size="icon-xs"
                className="hover:text-destructive"
                label={t("delete")}
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={14} />
              </IconButton>
              <IconButton variant="ghost" size="icon-xs" label={t("cancel")} onClick={exit}>
                <X size={14} />
              </IconButton>
            </span>
          </>
        ) : (
          <>
            <h2>{t(spec.title)}</h2>
            <span className="flex items-center gap-0.5">
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={t("chatNewGroup")}
                disabled={Boolean(writeBlocked)}
                disabledReason={writeBlocked?.reason}
                onClick={() => setCreatingGroup(true)}
              >
                <FolderPlus size={14} />
              </IconButton>
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={t("mediaSelectMode")}
                disabled={manageableSessions.length === 0}
                onClick={() => enterSelectMode()}
              >
                <ListChecks size={14} />
              </IconButton>
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={t(spec.newSession)}
                disabled={Boolean(writeBlocked)}
                disabledReason={writeBlocked?.reason}
                onClick={onCreate}
                loading={creating}
              >
                <Plus size={14} />
              </IconButton>
            </span>
          </>
        )}
      </div>
      <DndContext
        sensors={sensors}
        accessibility={dndAccessibility}
        collisionDetection={pointerWithin}
        onDragStart={(event: DragStartEvent) => setDraggingId(String(event.active.id))}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDraggingId(null)}
      >
      {/* 搜索只在真有东西可搜时出现 —— 空列表上摆一个搜索框是纯占位。
          ⌘K 那个全局搜索**不覆盖对话**(只有导航/项目/素材/工作流/发布),所以这里是
          找回一次旧对话的唯一入口。 */}
      {!selectMode && toolbar}
      {sessions.length > 0 && !selectMode && (
        <div className="relative shrink-0 px-3 py-3">
          <Search size={12} className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t(spec.searchPlaceholder)}
            aria-label={t(spec.searchPlaceholder)}
            className="h-9 w-full rounded-md border border-border bg-panel pl-7 pr-2 text-ui-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
      )}
      {/* 一列两段:上面是列表(分组 → 未分组 → 来自别处,**分组永远在最上面**),下面是空态。空态排在分组之后、
          占满剩下的高度并在其中居中 —— 此前它排在分组前面、整列居中:「来自别处」被挤到空态底下,空态贴着搜索框,
          下面一大片空着(维护者 2026-10-29 指出);建过分组时它干脆不出现,一排「某某 0」看不出这一类一条都没有。 */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden p-1.5">
        {/* 还没读到:铺一屏骨架,而不是一个看着像「一条都没有」的空格子(见 SessionListSkeleton)。
            空态那两句、分组计数都在这一支外面 —— 它们只说「确实没有」。 */}
        {showSkeleton && <SessionListSkeleton label={t(spec.loading)} />}
        {!showSkeleton && (
          <>
          <div className="grid shrink-0 grid-cols-[minmax(0,1fr)] content-start gap-1">
          {groupList.map((group) => {
            const members = byGroup.map.get(group.id) ?? [];
            // 搜索时把没命中的分组整段收起 —— 一排「某某 0」既占地方,又让人以为搜错了。
            // 不搜索时空分组要留着:刚建出来的那个得看得见,否则没地方往里拖。
            if (keyword && members.length === 0) return null;
            const isCollapsed = collapsed.has(group.id);
            return (
              <GroupSection key={group.id} groupId={group.id}>
                <ContextMenu>
                  <ContextMenuTrigger asChild>
                    <GroupToggle
                      open={!isCollapsed}
                      label={group.name}
                      count={members.length}
                      onClick={() =>
                        setCollapsed((current) => {
                          const next = new Set(current);
                          if (next.has(group.id)) next.delete(group.id);
                          else next.add(group.id);
                          return next;
                        })
                      }
                    />
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => setRenamingGroup(group)}>
                      <MenuItemBody icon={<Pencil />} label={t("rename")} description={writeBlocked?.brief} />
                    </ContextMenuItem>
                    <ContextMenuItem
                      className="text-destructive focus:text-destructive"
                      disabled={Boolean(writeBlocked)}
                      onSelect={() => setDeletingGroup(group)}
                    >
                      <MenuItemBody icon={<Trash2 />} label={t("delete")} description={writeBlocked?.brief} />
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
                {!isCollapsed && (
                  <div className="grid gap-1 pl-2">{members.map(renderSession)}</div>
                )}
              </GroupSection>
            );
          })}
          {/* 「未分组」这个小标题只在**真有分组**时才出现 —— 一个分组都没建过的人不该被告知
              他的对话"未分组"。 */}
          {groupList.length > 0 && byGroup.main.length > 0 && (
            // separator 变体 = 左右两条细线夹住中间那几个字。它本来就是 Marker 的
            //「带标签的分隔线」那一档 —— 这一段不是标题,是"下面这些没归到任何分组"的分界。
            <Marker variant="separator" className="px-1.5 pt-1">
              <MarkerContent className="text-ui-xs font-medium">
                {t("chatUngrouped")}
              </MarkerContent>
            </Marker>
          )}
          {byGroup.main.map(renderSession)}
          {aside && byGroup.aside.length > 0 && (
            <div className="grid gap-1 pt-1" data-session-aside="">
              <GroupToggle open={asideShown} label={aside.title} count={byGroup.aside.length} onClick={() => setAsideOpen(!asideOpen)} />
              {asideShown && byGroup.aside.map(renderSession)}
            </div>
          )}
          </div>
          {/* 「这里一条都没有」只看这里开的(分组里的也算这里开的;「来自别处」不算):分组都是空的也照说。 */}
          {(keyword ? visible.length === 0 : loaded && mainCount === 0) && (
            <div data-session-empty="" className="grid min-h-0 flex-1 place-items-center">
              {keyword ? (
                <EmptyState size="compact" icon={<SearchX size={15} />} title={t(spec.searchNoMatch)} />
              ) : (
                <EmptyState size="compact" icon={<MessageSquarePlus size={15} />} title={emptyTitle ?? t(spec.empty)} />
              )}
            </div>
          )}
          </>
        )}
      </div>
      {/* 拖起来时跟手的那一片 —— 没有它,拖动中的行只是原地变淡,看不出自己在拖什么。 */}
      <DragOverlay dropAnimation={null}>
        {draggingId ? (
          <Truncate as="div" className="rounded-md border border-border bg-panel px-2 py-1.5 text-xs font-semibold shadow-[var(--shadow-raised)]">
            {sessions.find((session) => session.id === draggingId)?.title}
          </Truncate>
        ) : null}
      </DragOverlay>
      </DndContext>

      <RenameDialog
        open={creatingGroup}
        title={t("chatNewGroup")}
        initialValue=""
        onCancel={() => setCreatingGroup(false)}
        pending={addGroup.isPending}
        onSubmit={(name) => addGroup.mutate(name)}
      />
      <RenameDialog
        open={renamingGroup !== null}
        title={t("chatRenameGroup")}
        initialValue={renamingGroup?.name ?? ""}
        onCancel={() => setRenamingGroup(null)}
        pending={editGroup.isPending}
        onSubmit={(name) => renamingGroup && editGroup.mutate({ id: renamingGroup.id, name })}
      />
      <ConfirmDialog
        open={deletingGroup !== null}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteGroupBody)}
        onCancel={() => setDeletingGroup(null)}
        pending={removeGroup.isPending}
        onConfirm={() => deletingGroup && removeGroup.mutate(deletingGroup.id)}
      />
      <RenameDialog
        open={renamingSession !== null}
        title={t(spec.renameTitle)}
        initialValue={renamingSession?.title ?? ""}
        onCancel={() => setRenamingSession(null)}
        pending={renameSession.isPending}
        onSubmit={(name) => renamingSession && renameSession.mutate({ id: renamingSession.id, name })}
      />
      <ConfirmDialog
        open={deletingSession !== null}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteBody)}
        onCancel={() => setDeletingSession(null)}
        pending={removeSession.isPending}
        onConfirm={() => deletingSession && removeSession.mutate(deletingSession.id)}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteManyBody).replace("{n}", String(selectedIds.size))}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate()}
      />
    </>
  );
}

/** 分组的一段:标题 + 成员。整段是放置目标 —— 拖到标题上(或空分组上)就收进来。 */
function GroupSection({ groupId, children }: { groupId: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: `group:${groupId}` });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "grid gap-0.5 rounded-md",
        isOver && "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--primary)_45%,transparent)]",
      )}
    >
      {children}
    </div>
  );
}

/** 会话行。可拖(排序 / 换组),可右键,选择模式下点它是勾选而不是打开。只能看的那种三样都没有,只能打开。 */
function SessionRow({
  session,
  extras,
  viewOnly,
  groups,
  active,
  selectMode,
  checked,
  dragging,
  workspaceId,
  onOpen,
  onRename,
  onDelete,
  onMove,
  onNewGroup,
  kind,
}: {
  session: ListedSession;
  extras: SessionRowExtras | null;
  /** 同事共享来、只能看的会话:这一行怎么说它。 */
  viewOnly?: MessageKey;
  groups: SessionGroup[];
  kind: SessionGroupKind;
  active: boolean;
  selectMode: boolean;
  checked: boolean;
  dragging: boolean;
  workspaceId: string;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
  onMove: (groupId: string | null) => void;
  onNewGroup: () => void;
}) {
  const t = useI18n();
  //: 点下去到那一处真出现之间(ComfyUI 工作台:读那台机器的工作流库、起本机服务、亮视图、把那一张读进画布)可能好几秒到
  //: 一两分钟 —— 这一行自己把这段说出来,不然点下去像没反应(维护者:「要过一阵子才会成功跳转,容易让人误解」)。
  //: `opening` 是这一段本身,`starting` 是那台机器背后的本机服务真要起(第一次启动最久,说明里再补一句)。
  const [going, setGoing] = React.useState<"idle" | "opening" | "starting">("idle");
  const goingRef = React.useRef(false);
  const goBackAction = extras?.goBack ?? null;
  const goBackTo = () => {
    //: 转着的时候再点不去第二次(禁用只管得住鼠标,这里再挡一道:连点只叫一次桥)
    if (!goBackAction || goingRef.current) return;
    goingRef.current = true;
    setGoing("opening");
    void (async () => {
      try {
        //: 失败由给这一颗的人说话(见 SessionRowExtras.goBack),这里只保证圈一定收掉 —— 不留一个转不完的圈
        await goBackAction.onClick(() => setGoing("starting"));
      } finally {
        goingRef.current = false;
        setGoing("idle");
      }
    })();
  };
  // 选择模式下不许拖:那时的点击是"勾选",两种手势叠在一起谁都做不好。只能看的也不许拖(拖动是换分组)。
  const { attributes, listeners, setNodeRef } = useDraggable({ id: session.id, disabled: selectMode || Boolean(viewOnly) });
  //: 行那一层的样子(圆角、底色、左边那条短竖条、拖起来的淡影)。**贴在最外层** ——
  //: 铺满整行才叫「这一行被选中了」,包括右边那颗「回到那里」(维护者:「背景要覆盖整一行,
  //: 右侧回到那里没有被包裹进去」)。
  const chrome = cn(
    "w-full rounded-md transition-colors duration-100",
    // 选中态:一条**圆角短竖条**贴在左边 + 一层很淡的底色。此前是
    // `shadow-[inset_2px_0_0]` —— 直角、贯穿整行高、颜色还是实心 primary,
    // 在一堆圆角行里显得很硬。圆角竖条是本仓库已有的做法(剪辑页字幕条同款)。
    active
      ? "relative bg-[color-mix(in_srgb,var(--primary)_9%,transparent)] before:absolute before:inset-y-1.5 before:left-0.5 before:w-0.5 before:rounded-full before:bg-primary before:content-[''] hover:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]"
      : "hover:bg-muted",
    // 拖起来的那一条留个淡影占位,别让列表塌下去。
    dragging && "opacity-40",
  );
  //: 里面那颗按钮只管内容与点击(内边距留在它身上:连它一起可点)。行那一层的样子由外层给。
  const rowButton = (extra: string) => (
    <button
      ref={setNodeRef}
      type="button"
      className={cn(
        SESSION_ROW_BODY,
        "cursor-pointer",
        selectMode && "grid-cols-[auto_minmax(0,1fr)] gap-1.5",
        extra,
      )}
      onClick={onOpen}
      {...attributes}
      {...listeners}
    >
      {/* 列表行用**前导勾选框**,不是卡片那种右上角浮标(components/app/SelectionCheck):
          那个是为卡片定的位置与尺寸,压在一行 28px 高的标题上会把字盖掉。 */}
      {selectMode && (
        <Checkbox checked={checked} disabled={Boolean(viewOnly)} className="pointer-events-none" tabIndex={-1} />
      )}
      <span className="grid min-w-0 gap-0.5">
        <span className="flex min-w-0 items-center gap-1.5">
          {/* 有小标时标题占满、小标靠右对齐成一列;没有时照旧(只读的那枚眼睛跟在标题后面) */}
          <Truncate className={cn("text-ui-sm", extras?.badge && "min-w-0 flex-1")}>{session.title}</Truncate>
          {viewOnly && <Eye size={12} className="shrink-0 text-muted-foreground" aria-hidden />}
          {extras?.badge}
        </span>
        {extras?.subtitle && <Truncate className="text-ui-xs text-muted-foreground">{extras.subtitle}</Truncate>}
      </span>
    </button>
  );
  //: 「回到那里」和这一行并排,不塞进行按钮里(按钮里套按钮,读屏念成一个、点它连带打开这一行)。
  //: 两个都是**兄弟**按钮,点它不会连带打开这一行(维护者:「点击回到那里...点击还是独立的」);
  //: 行那一层的样子在外层 div 上,所以选中底色照样盖住它。
  const goBack = extras?.goBack && !selectMode ? (
    <IconButton
      variant="ghost"
      size="icon-xs"
      className="mr-1 text-muted-foreground"
      //: 在去的那段时间里,这一颗自己就是那句话说的地方:名字换成「正在启动…」,箭头换成转圈(一样高,行不跳);
      //: 真要去起本机服务时(第一次启动可能要一两分钟)再把这话说全 —— 都是既有的文案(localServices)。
      label={going === "idle" ? extras.goBack.label : t("localServiceOpenStarting")}
      hint={going === "idle" ? extras.goBack.hint : null}
      disabledReason={going === "starting" ? t("localServiceStartingNote") : undefined}
      disabled={going !== "idle"}
      loading={going !== "idle"}
      onClick={goBackTo}
    >
      <CornerUpLeft size={13} />
    </IconButton>
  ) : null;
  //: 有一句话 / 一颗按钮要多说时:外面那一格拿行样子(chrome),里面那颗按钮只管自己的内容。
  //: `data-session-row` 挂在「整行」那一层上(底色、竖条、拖影都在它身上)。
  const line = goBack ? (
    <div data-session-row className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-0.5", chrome)}>
      {viewOnly ? (
        <Hint label={session.title} hint={t(viewOnly)}>
          {rowButton("")}
        </Hint>
      ) : (
        rowButton("")
      )}
      {goBack}
    </div>
  ) : rowButton(chrome);
  //: 只能看的没有右键菜单:改名、收纳、删除都是主人的事,共享与否也是(SessionShareMenuItem 本来就藏)。
  //: 悬停说全名和「为什么只能看」。(有「回到那里」时那一层已经套在按钮外面了,见上面的 line。)
  if (viewOnly) return goBack ? line : <Hint label={session.title} hint={t(viewOnly)}>{line}</Hint>;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{line}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onRename}>
          <MenuItemBody icon={<Pencil />} label={t("rename")} />
        </ContextMenuItem>
        <ContextMenuSub>
          {/* 图标不能省:SubTrigger 和普通项共用 gap-2 + 图标槽的排版,没图标时标签会顶到
              图标列上,和上下两条对不齐(真机可见)。 */}
          <ContextMenuSubTrigger>
            <MenuItemBody icon={<FolderInput />} label={t("chatMoveToGroup")} />
          </ContextMenuSubTrigger>
          <ContextMenuSubContent>
            {groups.map((group) => (
              <ContextMenuItem
                key={group.id}
                disabled={session.group_id === group.id}
                onSelect={() => onMove(group.id)}
              >
                <MenuItemBody inset label={group.name} truncate />
              </ContextMenuItem>
            ))}
            {groups.length > 0 && <ContextMenuSeparator />}
            <ContextMenuItem disabled={!session.group_id} onSelect={() => onMove(null)}>
              <MenuItemBody inset label={t("chatUngrouped")} />
            </ContextMenuItem>
            <ContextMenuItem onSelect={onNewGroup}>
              <MenuItemBody icon={<FolderPlus />} label={t("chatNewGroup")} />
            </ContextMenuItem>
          </ContextMenuSubContent>
        </ContextMenuSub>
        <SessionShareMenuItem
          session={session}
          kind={SESSION_KINDS[kind].shareKind}
          workspaceId={workspaceId}
          queryKey={SESSION_KINDS[kind].sessionsQueryKey}
        />
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          <MenuItemBody icon={<Trash2 />} label={t("delete")} />
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
