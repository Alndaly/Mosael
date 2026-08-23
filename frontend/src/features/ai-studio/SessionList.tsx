import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronRight, FolderInput, FolderPlus, ListChecks, MessageSquarePlus, Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createSessionGroup,
  deleteAgentSession,
  deleteSessionGroup,
  listSessionGroups,
  moveSessionToGroup,
  renameSessionGroup,
  reorderSessions,
  type AgentSessionGroup,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
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
import { SessionShareMenuItem } from "@/features/ai-studio/SessionShareMenuItem";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { cn } from "@/lib/utils";

type AgentSession = components["schemas"]["AgentSessionOut"];

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
  workspaceId,
  sessions,
  loaded,
  activeSessionId,
  onSelect,
  onCreate,
  creating,
  onDeleted,
}: {
  workspaceId: string;
  sessions: AgentSession[];
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
  const [renamingSession, setRenamingSession] = React.useState<AgentSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<AgentSession | null>(null);
  const [renamingGroup, setRenamingGroup] = React.useState<AgentSessionGroup | null>(null);
  const [deletingGroup, setDeletingGroup] = React.useState<AgentSessionGroup | null>(null);
  const [creatingGroup, setCreatingGroup] = React.useState(false);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  // 折叠状态只活在这次会话里:它是"我现在不想看这一摞",不是设置。
  const [collapsed, setCollapsed] = React.useState<Set<string>>(new Set());

  const groups = useQuery({
    queryKey: ["agent-session-groups", workspaceId],
    queryFn: () => listSessionGroups(workspaceId),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["agent-sessions", workspaceId] });
    void qc.invalidateQueries({ queryKey: ["agent-session-groups", workspaceId] });
  };

  const { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, exit } = useMultiSelect(
    sessions,
    (session) => session.id,
  );

  const renameSession = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api(`/api/agent/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ title: name }) }),
    onSuccess: () => {
      setRenamingSession(null);
      refresh();
    },
  });
  const removeSession = useMutation({
    mutationFn: (id: string) => deleteAgentSession(id),
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
          await deleteAgentSession(id);
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
    mutationFn: (name: string) => createSessionGroup(workspaceId, name),
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
    mutationFn: ({ id, groupId }: { id: string; groupId: string | null }) => moveSessionToGroup(id, groupId),
    onSuccess: refresh,
  });

  const reorder = useMutation({
    mutationFn: ({ groupId, orderedIds }: { groupId: string | null; orderedIds: string[] }) =>
      reorderSessions(workspaceId, groupId, orderedIds),
    // 乐观更新已经把界面摆好了(见 onDragEnd),这里只在落库后对一次账。
    onSettled: refresh,
  });

  const groupList = groups.data ?? [];
  // 分组内 / 未分组两摞。会话本身的顺序(后端按 updated_at 倒序)在每一摞里保持不变。
  const byGroup = React.useMemo(() => {
    const map = new Map<string, AgentSession[]>();
    const loose: AgentSession[] = [];
    for (const session of sessions) {
      const groupId = session.group_id;
      if (groupId && groupList.some((group) => group.id === groupId)) {
        map.set(groupId, [...(map.get(groupId) ?? []), session]);
      } else {
        loose.push(session);
      }
    }
    return { map, loose };
  }, [sessions, groupList]);

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
    const from = containerOf(activeId);
    // 落在分组标题上 = 收进那个分组的末尾(空分组、折叠着的分组都只能这样接)。
    const to = overId.startsWith("group:") ? overId.slice("group:".length) : containerOf(overId);
    const target = [...(containers[to] ?? [])].filter((id) => id !== activeId);
    const index = overId.startsWith("group:") ? target.length : Math.max(0, target.indexOf(overId));
    target.splice(index, 0, activeId);
    if (from === to && target.join() === (containers[to] ?? []).join()) return;

    // 先把界面摆好再落库:等一个来回的话,松手那一刻会看到它弹回原位。
    const groupId = to === UNGROUPED ? null : to;
    qc.setQueryData<AgentSession[]>(["agent-sessions", workspaceId], (old) => {
      if (!old) return old;
      const byId = new Map(old.map((session) => [session.id, session]));
      const next: AgentSession[] = [];
      const order = { ...containers, [to]: target, [from]: containers[from].filter((id) => id !== activeId) };
      for (const key of [...groupList.map((group) => group.id), UNGROUPED]) {
        for (const id of order[key] ?? []) {
          const session = byId.get(id);
          if (session) next.push({ ...session, group_id: key === UNGROUPED ? null : key });
        }
      }
      return next;
    });
    reorder.mutate({ groupId, orderedIds: target });
  };

  const renderSession = (session: AgentSession) => (
    <SessionRow
      key={session.id}
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
      <div className="flex min-h-10 items-center justify-between gap-1 border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-ui-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
        {selectMode ? (
          // 选择模式下头部换成这一批的动作 —— 和素材/工作流/发布三页同一套语汇。
          <>
            <h2>{t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}</h2>
            <span className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                title={allSelected(sessions) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                aria-label={allSelected(sessions) ? t("mediaDeselectAll") : t("mediaSelectAll")}
                onClick={() => selectAll(sessions)}
              >
                <ListChecks size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 hover:text-destructive"
                title={t("delete")}
                aria-label={t("delete")}
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={14} />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7" title={t("cancel")} aria-label={t("cancel")} onClick={exit}>
                <X size={14} />
              </Button>
            </span>
          </>
        ) : (
          <>
            <h2>{t("chatSessionsTitle")}</h2>
            <span className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                title={t("chatNewGroup")}
                aria-label={t("chatNewGroup")}
                onClick={() => setCreatingGroup(true)}
              >
                <FolderPlus size={14} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                title={t("mediaSelectMode")}
                aria-label={t("mediaSelectMode")}
                disabled={sessions.length === 0}
                onClick={() => setSelectMode(true)}
              >
                <ListChecks size={14} />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="h-7 w-7"
                title={t("chatNewSession")}
                aria-label={t("chatNewSession")}
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
      <div
        className={cn(
          "grid content-start gap-1 overflow-auto p-1.5 [scrollbar-gutter:stable] [scrollbar-width:none] hover:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] hover:[scrollbar-width:thin] focus-within:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] focus-within:[scrollbar-width:thin] [&::-webkit-scrollbar]:h-0 [&::-webkit-scrollbar]:w-0 hover:[&::-webkit-scrollbar]:h-1.5 hover:[&::-webkit-scrollbar]:w-1.5 focus-within:[&::-webkit-scrollbar]:h-1.5 focus-within:[&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
          loaded && sessions.length === 0 && groupList.length === 0 && "content-center justify-items-center",
        )}
      >
        {loaded && sessions.length === 0 && groupList.length === 0 && (
          <EmptyState size="compact" icon={<MessageSquarePlus size={15} />} title={t("chatNoSessions")} />
        )}
        {groupList.map((group) => {
          const members = byGroup.map.get(group.id) ?? [];
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
                <SortableContext items={containers[group.id] ?? []} strategy={verticalListSortingStrategy}>
                  <div className="grid gap-1 pl-2">{members.map(renderSession)}</div>
                </SortableContext>
              )}
            </GroupSection>
          );
        })}
        {/* 「未分组」这个小标题只在**真有分组**时才出现 —— 一个分组都没建过的人不该被告知
            他的对话"未分组"。 */}
        {groupList.length > 0 && byGroup.loose.length > 0 && (
          <span className="px-1.5 pt-1 text-ui-2xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            {t("chatUngrouped")}
          </span>
        )}
        <SortableContext items={containers[UNGROUPED] ?? []} strategy={verticalListSortingStrategy}>
          {byGroup.loose.map(renderSession)}
        </SortableContext>
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
        body={t("chatDeleteGroupBody")}
        onCancel={() => setDeletingGroup(null)}
        onConfirm={() => deletingGroup && removeGroup.mutate(deletingGroup.id)}
      />
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
        onConfirm={() => deletingSession && removeSession.mutate(deletingSession.id)}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("chatDeleteSessionsBody").replace("{n}", String(selectedIds.size))}
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
}: {
  session: AgentSession;
  groups: AgentSessionGroup[];
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
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({
    id: session.id,
    disabled: selectMode,
  });
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <button
          ref={setNodeRef}
          type="button"
          style={{ transform: CSS.Transform.toString(transform), transition }}
          className={cn(
            "grid w-full cursor-pointer grid-cols-[minmax(0,1fr)] items-center gap-px rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted",
            selectMode && "grid-cols-[auto_minmax(0,1fr)] gap-1.5",
            active && "bg-accent shadow-[inset_2px_0_0_var(--primary)] hover:bg-accent",
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
          <strong className="truncate text-xs font-semibold">{session.title}</strong>
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
        <SessionShareMenuItem session={session} kind="agent_session" workspaceId={workspaceId} queryKey="agent-sessions" />
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          <Trash2 /> {t("delete")}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
