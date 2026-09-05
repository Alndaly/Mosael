import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { ChevronRight, FolderInput, FolderPlus, ListChecks, MessageSquarePlus, Pencil, Plus, Search, SearchX, Trash2, X } from "lucide-react";
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
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
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
import { Marker, MarkerContent } from "@/components/ui/marker";
import { SessionShareMenuItem } from "@/features/ai-studio/SessionShareMenuItem";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { cn } from "@/lib/utils";

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
  searchPlaceholder: MessageKey;
  searchNoMatch: MessageKey;
  renameTitle: MessageKey;
  deleteBody: MessageKey;
  deleteGroupBody: MessageKey;
  /** 批量删。措辞里带数量和「会一并删掉什么」—— 两种会话删掉的东西不一样。 */
  deleteManyBody: MessageKey;
}

const SESSION_KINDS: Record<SessionGroupKind, SessionKindSpec> = {
  agent: {
    sessionsQueryKey: "agent-sessions",
    path: (id: string) => `/api/agent/sessions/${id}`,
    shareKind: "agent_session" as const,
    title: "chatSessionsTitle",
    newSession: "chatNewSession",
    empty: "chatNoSessions",
    searchPlaceholder: "chatSearchSessions",
    searchNoMatch: "chatSearchNoMatch",
    renameTitle: "renameSession",
    deleteBody: "deleteSessionBody",
    deleteGroupBody: "chatDeleteGroupBody",
    deleteManyBody: "chatDeleteSessionsBody",
  },
  generation: {
    sessionsQueryKey: "generation-sessions",
    path: (id: string) => `/api/generation/sessions/${id}`,
    shareKind: "generation_session" as const,
    title: "generationSessionsTitle",
    newSession: "generationNewSession",
    empty: "generationNoSessions",
    searchPlaceholder: "generationSearchSessions",
    searchNoMatch: "generationSearchNoMatch",
    renameTitle: "renameGenerationSession",
    deleteBody: "deleteGenerationSessionBody",
    deleteGroupBody: "generationDeleteGroupBody",
    deleteManyBody: "generationDeleteSessionsBody",
  },
};

/** 收进分组;`null` = 移出分组(接口用空串表达"改成没有")。 */
function moveSessionToGroup(kind: SessionGroupKind, sessionId: string, groupId: string | null): Promise<unknown> {
  return api(SESSION_KINDS[kind].path(sessionId), {
    method: "PATCH",
    body: JSON.stringify({ group_id: groupId ?? "" }),
  });
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
export function SessionList({
  kind,
  workspaceId,
  sessions,
  loaded,
  activeSessionId,
  onSelect,
  onCreate,
  creating,
  onDeleted,
}: {
  /** 对话还是生成 —— 两边各自一套分组,差异全在 SESSION_KINDS 那张表里。 */
  kind: SessionGroupKind;
  workspaceId: string;
  sessions: ListedSession[];
  loaded: boolean;
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  creating: boolean;
  /** 删掉了这些会话 —— 当前打开的那个若在其中,调用方要把它从视图里放下。 */
  onDeleted: (ids: string[]) => void;
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

  const groups = useQuery({
    queryKey: ["session-groups", kind, workspaceId],
    queryFn: () => listSessionGroups(workspaceId, kind),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: [spec.sessionsQueryKey, workspaceId] });
    void qc.invalidateQueries({ queryKey: ["session-groups", kind, workspaceId] });
  };

  const { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, exit } = useMultiSelect(
    sessions,
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
  // 分组内 / 未分组两摞。会话本身的顺序(后端按 updated_at 倒序)在每一摞里保持不变。
  const byGroup = React.useMemo(() => {
    const map = new Map<string, ListedSession[]>();
    const loose: ListedSession[] = [];
    for (const session of visible) {
      const groupId = session.group_id;
      if (groupId && groupList.some((group) => group.id === groupId)) {
        map.set(groupId, [...(map.get(groupId) ?? []), session]);
      } else {
        loose.push(session);
      }
    }
    return { map, loose };
  }, [visible, groupList]);

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
    // 先把界面摆好再落库:等一个来回的话,松手那一刻会看到它弹回原位。
    qc.setQueryData<ListedSession[]>([spec.sessionsQueryKey, workspaceId], (old) =>
      old?.map((session) => (session.id === activeId ? { ...session, group_id: groupId } : session)),
    );
    moveSession.mutate({ id: activeId, groupId });
  };

  const renderSession = (session: ListedSession) => (
    <SessionRow
      key={session.id}
      kind={kind}
      session={session}
      groups={groupList}
      active={!selectMode && activeSessionId === session.id}
      selectMode={selectMode}
      checked={selectedIds.has(session.id)}
      dragging={draggingId === session.id}
      workspaceId={workspaceId}
      onOpen={() => (selectMode ? toggle(session.id) : onSelect(session.id))}
      onRename={() => setRenamingSession(session)}
      onDelete={() => setDeletingSession(session)}
      onMove={(groupId) => moveSession.mutate({ id: session.id, groupId })}
      onNewGroup={() => setCreatingGroup(true)}
    />
  );

  return (
    <>
      <div className="flex min-h-10 shrink-0 items-center justify-between gap-1 border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-ui-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
        {selectMode ? (
          // 选择模式下头部换成这一批的动作 —— 和素材/工作流/发布三页同一套语汇。
          <>
            <h2>{t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}</h2>
            <span className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon-xs"
                title={allSelected(visible) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                aria-label={allSelected(visible) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                onClick={() => selectAll(visible)}
              >
                <ListChecks size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                className="hover:text-destructive"
                title={t("delete")}
                aria-label={t("delete")}
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={14} />
              </Button>
              <Button variant="ghost" size="icon-xs" title={t("cancel")} aria-label={t("cancel")} onClick={exit}>
                <X size={14} />
              </Button>
            </span>
          </>
        ) : (
          <>
            <h2>{t(spec.title)}</h2>
            <span className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon-xs"
                title={t("chatNewGroup")}
                aria-label={t("chatNewGroup")}
                onClick={() => setCreatingGroup(true)}
              >
                <FolderPlus size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                title={t("mediaSelectMode")}
                aria-label={t("mediaSelectMode")}
                disabled={sessions.length === 0}
                onClick={() => setSelectMode(true)}
              >
                <ListChecks size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                title={t(spec.newSession)}
                aria-label={t(spec.newSession)}
                onClick={onCreate}
                loading={creating}
              >
                <Plus size={14} />
              </Button>
            </span>
          </>
        )}
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={(event: DragStartEvent) => setDraggingId(String(event.active.id))}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDraggingId(null)}
      >
      {/* 搜索只在真有东西可搜时出现 —— 空列表上摆一个搜索框是纯占位。
          ⌘K 那个全局搜索**不覆盖对话**(只有导航/项目/素材/工作流/发布),所以这里是
          找回一次旧对话的唯一入口。 */}
      {sessions.length > 0 && !selectMode && (
        <div className="relative shrink-0 border-b border-border px-2 py-1.5">
          <Search size={12} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t(spec.searchPlaceholder)}
            aria-label={t(spec.searchPlaceholder)}
            className="h-7 w-full rounded-md border border-transparent bg-field pl-6 pr-2 text-ui-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
      )}
      <div
        className={cn(
          "grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-1 overflow-y-auto overflow-x-hidden p-1.5",
          loaded && ((sessions.length === 0 && groupList.length === 0) || (Boolean(keyword) && visible.length === 0)) &&
            "content-center justify-items-center",
        )}
      >
        {loaded && sessions.length === 0 && groupList.length === 0 && (
          <EmptyState size="compact" icon={<MessageSquarePlus size={15} />} title={t(spec.empty)} />
        )}
        {keyword && visible.length === 0 && (
          <EmptyState size="compact" icon={<SearchX size={15} />} title={t(spec.searchNoMatch)} />
        )}
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
                  <button
                    type="button"
                    className="flex w-full cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-1.5 py-1 text-left text-ui-2xs font-semibold uppercase tracking-[0.06em] text-muted-foreground transition-colors duration-100 hover:bg-muted"
                    onClick={() =>
                      setCollapsed((current) => {
                        const next = new Set(current);
                        if (next.has(group.id)) next.delete(group.id);
                        else next.add(group.id);
                        return next;
                      })
                    }
                  >
                    <ChevronRight
                      size={11}
                      className={cn("shrink-0 transition-transform duration-[120ms]", !isCollapsed && "rotate-90")}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate normal-case" title={group.name}>
                      {group.name}
                    </span>
                    <span className="shrink-0 tabular-nums">{members.length}</span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => setRenamingGroup(group)}>
                    <Pencil /> {t("rename")}
                  </ContextMenuItem>
                  <ContextMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={() => setDeletingGroup(group)}
                  >
                    <Trash2 /> {t("delete")}
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
        {groupList.length > 0 && byGroup.loose.length > 0 && (
          // separator 变体 = 左右两条细线夹住中间那几个字。它本来就是 Marker 的
          //「带标签的分隔线」那一档 —— 这一段不是标题,是"下面这些没归到任何分组"的分界。
          <Marker variant="separator" className="px-1.5 pt-1">
            <MarkerContent className="text-ui-2xs font-semibold uppercase tracking-[0.06em]">
              {t("chatUngrouped")}
            </MarkerContent>
          </Marker>
        )}
        {byGroup.loose.map(renderSession)}
      </div>
      {/* 拖起来时跟手的那一片 —— 没有它,拖动中的行只是原地变淡,看不出自己在拖什么。 */}
      <DragOverlay dropAnimation={null}>
        {draggingId ? (
          <div className="truncate rounded-md border border-border bg-panel px-2 py-1.5 text-xs font-semibold shadow-[var(--shadow-raised)]">
            {sessions.find((session) => session.id === draggingId)?.title}
          </div>
        ) : null}
      </DragOverlay>
      </DndContext>

      <RenameDialog
        open={creatingGroup}
        title={t("chatNewGroup")}
        initialValue=""
        onCancel={() => setCreatingGroup(false)}
        onSubmit={(name) => addGroup.mutate(name)}
      />
      <RenameDialog
        open={renamingGroup !== null}
        title={t("chatRenameGroup")}
        initialValue={renamingGroup?.name ?? ""}
        onCancel={() => setRenamingGroup(null)}
        onSubmit={(name) => renamingGroup && editGroup.mutate({ id: renamingGroup.id, name })}
      />
      <ConfirmDialog
        open={deletingGroup !== null}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteGroupBody)}
        onCancel={() => setDeletingGroup(null)}
        onConfirm={() => deletingGroup && removeGroup.mutate(deletingGroup.id)}
      />
      <RenameDialog
        open={renamingSession !== null}
        title={t(spec.renameTitle)}
        initialValue={renamingSession?.title ?? ""}
        onCancel={() => setRenamingSession(null)}
        onSubmit={(name) => renamingSession && renameSession.mutate({ id: renamingSession.id, name })}
      />
      <ConfirmDialog
        open={deletingSession !== null}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteBody)}
        onCancel={() => setDeletingSession(null)}
        onConfirm={() => deletingSession && removeSession.mutate(deletingSession.id)}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t(spec.deleteManyBody).replace("{n}", String(selectedIds.size))}
        onCancel={() => setBatchDeleting(false)}
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

/** 会话行。可拖(排序 / 换组),可右键,选择模式下点它是勾选而不是打开。 */
function SessionRow({
  session,
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
  // 选择模式下不许拖:那时的点击是"勾选",两种手势叠在一起谁都做不好。
  const { attributes, listeners, setNodeRef } = useDraggable({ id: session.id, disabled: selectMode });
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <button
          ref={setNodeRef}
          type="button"
          className={cn(
            "grid w-full cursor-pointer grid-cols-[minmax(0,1fr)] items-center gap-px rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted",
            selectMode && "grid-cols-[auto_minmax(0,1fr)] gap-1.5",
            // 选中态:一条**圆角短竖条**贴在左边 + 一层很淡的底色。此前是
            // `shadow-[inset_2px_0_0]` —— 直角、贯穿整行高、颜色还是实心 primary,
            // 在一堆圆角行里显得很硬。圆角竖条是本仓库已有的做法(剪辑页字幕条同款)。
            active &&
              "relative bg-[color-mix(in_srgb,var(--primary)_9%,transparent)] before:absolute before:inset-y-1.5 before:left-0.5 before:w-0.5 before:rounded-full before:bg-primary before:content-[''] hover:bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]",
            // 拖起来的那一条留个淡影占位,别让列表塌下去。
            dragging && "opacity-40",
          )}
          onClick={onOpen}
          {...attributes}
          {...listeners}
        >
          {/* 列表行用**前导勾选框**,不是卡片那种右上角浮标(components/app/SelectionCheck):
              那个是为卡片定的位置与尺寸,压在一行 28px 高的标题上会把字盖掉。 */}
          {selectMode && <Checkbox checked={checked} className="pointer-events-none" tabIndex={-1} />}
          <span className="truncate text-xs">{session.title}</span>
        </button>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onRename}>
          <Pencil /> {t("rename")}
        </ContextMenuItem>
        <ContextMenuSub>
          {/* 图标不能省:SubTrigger 和普通项共用 gap-2 + 图标槽的排版,没图标时标签会顶到
              图标列上,和上下两条对不齐(真机可见)。 */}
          <ContextMenuSubTrigger>
            <FolderInput /> {t("chatMoveToGroup")}
          </ContextMenuSubTrigger>
          <ContextMenuSubContent>
            {groups.map((group) => (
              <ContextMenuItem
                key={group.id}
                disabled={session.group_id === group.id}
                onSelect={() => onMove(group.id)}
              >
                {group.name}
              </ContextMenuItem>
            ))}
            {groups.length > 0 && <ContextMenuSeparator />}
            <ContextMenuItem disabled={!session.group_id} onSelect={() => onMove(null)}>
              {t("chatUngrouped")}
            </ContextMenuItem>
            <ContextMenuItem onSelect={onNewGroup}>
              <FolderPlus /> {t("chatNewGroup")}
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
          <Trash2 /> {t("delete")}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
