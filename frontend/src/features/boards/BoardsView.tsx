import { CanvasToolbar, CanvasToolbarGroup } from "@/components/app/CanvasToolbar";
import { ActionMenu } from "@/components/layout/ActionMenu";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import React from "react";
import { useOpenRequest } from "@/lib/deepLink";
import { CARD_GRID, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { CanvasPreview } from "@/components/layout/CanvasPreview";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Check, CheckSquare, Copy, LayoutGrid, ListChecks, Map as MapIcon, Maximize2, Pencil, Plus, Redo2, Trash2, Undo2, X } from "lucide-react";
import { toast } from "sonner";

import {
  api as api2,
  ApiError,
  createBoard,
  deleteBoard,
  duplicateBoard,
  generateOnBoard,
  grabAssetFrame,
  speakOnBoard,
  trimOnBoard,
  writeOnBoard,
  getBoard,
  importAsset,
  addComment,
  deleteComment,
  moveComment,
  listComments,
  listMembers,
  listBoards,
  updateBoard,
  type GenerationOption,
  type Board,
  type BoardCanvas as Canvas,
  type BoardItem,
  type Workspace,
  type CollaborationComment,
} from "@/api/client";
import { useAuth } from "@/app/auth";
import type { MediaKind } from "@/features/boards/boardNodes";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { CanvasTitle } from "@/components/app/canvasTitle";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { CanvasDetailLoading } from "@/components/layout/CanvasDetailLoading";
import { CanvasCardSkeleton } from "@/components/layout/CanvasCardSkeleton";
import { relativeTime } from "@/lib/time";
import { usePersistentSelection, usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { CanvasAgentChat, type CanvasAgentMode } from "@/features/agent/CanvasAgentChat";
import {
  canvasDockedPanelEdges,
  canvasRightDockOcclusion,
} from "@/components/app/canvasPanelLayout";
import { RightDockResizeHandle } from "@/components/app/RightDockResizeHandle";
import { useResizableSidebar } from "@/lib/useResizableSidebar";
import { AnnotationControls } from "@/features/markers/AnnotationControls";
import { MarkerListButton } from "@/features/markers/MarkerListButton";
import { canvasInsets } from "@/components/app/fitCanvasViewport";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { useAutosave } from "@/lib/useAutosave";
import { AssetPickerDialog } from "@/features/boards/AssetPickerDialog";
import { ScenePickerDialog } from "@/features/scenes/ScenePickerDialog";
import { boardSettlementPatch, itemError, itemIsRunning, itemJobId } from "@/features/boards/boardItemState";
import { runNoteWrite, type NoteWriteInput } from "@/features/boards/noteWriteLifecycle";
import { CollaborationSheet } from "@/features/collaboration/CollaborationSheet";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { EdgeShapeToggle, useEdgeShape } from "@/components/app/canvasEdgeShape";
import { CanvasNodeSearch, type CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import { boardSearchEntries } from "@/features/boards/boardSearch";

/**
 * 创意画板:除了和智能体对话之外,另一条把想法摊开的路。
 *
 * 对话是线性的 —— 一句接一句,回头找上一个念头要往回翻。画板是空间的:碎片摆在那儿,
 * 挪一挪就看出哪些是一组、哪些还缺一块。两者不是替代关系,是同一个人在不同阶段要的两种东西。
 *
 * **和工作流分开,不共用一个画布组件。** 看着都是"节点 + 连线",但工作流的节点是**会执行的
 * 步骤**(有必填、有运行态、有类型校验),画板上的是**一个想法**(要能随手改色、双击就写字)。
 * 硬凑成一个的话,每加一个画板专属的交互都要先绕过工作流那一套 —— 见 boardNodes 里的说明。
 */
export function BoardsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const queryClient = useQueryClient();

  const boards = useQuery({
    queryKey: ["boards", workspace.id],
    queryFn: () => listBoards(workspace.id),
  });
  const list = React.useMemo(() => boards.data ?? [], [boards.data]);
  // 选中的那张活过导航 —— 切走再回来还在原来那张板上(和工作流、插件同一套)。
  const [openId, setOpenId, openSelection] = usePersistentSelection(
    `boards:${workspace.id}`,
    boards.data?.map((board) => board.id),
  );
  const open = list.find((board) => board.id === openId) ?? null;
  React.useEffect(() => { const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("board"); if (id && list.some(b => b.id === id)) { setOpenId(id); history.replaceState(null, "", "#/boards"); } }, [list, setOpenId]);
  // 那一张还没加载出来时接不住 —— 返回 false,请求留在信箱里,列表到货后再投(见 lib/deepLink)。
  useOpenRequest("mosael:open-board", (id) => {
    if (!list.some((b) => b.id === id)) return false;
    setOpenId(id);
  }, [list]);

  const create = useMutation({
    mutationFn: () => createBoard({ workspace_id: workspace.id }),
    onSuccess: (board) => {
      void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] });
      setOpenId(board.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const refreshList = () => void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] });

  //: 卡片上的单条动作(「⋯」菜单与右键菜单共用):打开、重命名、创建副本、删除。
  const [menuRenaming, setMenuRenaming] = React.useState<Board | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<Board | null>(null);
  const remove = useMutation({
    mutationFn: (boardId: string) => deleteBoard(boardId, workspace.id),
    onSuccess: () => {
      setMenuDeleting(null);
      refreshList();
    },
    // 失败时确认框留着,可以重试或取消。
    onError: (error: Error) => toast.error(error.message),
  });
  const rename = useMutation({
    //: 带着列表里那份 revision 去改:画板开在别处、刚被改过的话,这次改名会撞上 409,
    //: 而不是把别处的新画布悄悄盖掉(改名和存画布走的是同一个 CAS 口子)。
    mutationFn: ({ board, name }: { board: Board; name: string }) =>
      updateBoard(board.id, { workspace_id: workspace.id, base_revision: board.revision, name }),
    onSuccess: () => {
      setMenuRenaming(null);
      refreshList();
    },
    onError: (error: Error) => {
      refreshList();
      toast.error(error instanceof ApiError && error.status === 409 ? t("boardsCanvasConflict") : error.message);
    },
  });
  const duplicate = useMutation({
    //: 「× 副本」是界面语言里的一句话,在这里按当前语言拼好再交给后端。
    mutationFn: (board: Board) =>
      duplicateBoard(board.id, { workspace_id: workspace.id, name: t("boardsCopyName").replace("{name}", board.name) }),
    onSuccess: (made) => {
      refreshList();
      toast.success(t("boardsDuplicated").replace("{name}", made.name));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // 多选与首页、素材、工作流同一份状态机(见 lib/useMultiSelect):退出即清空、被删掉的自动剔除。
  const { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, exit } = useMultiSelect(list, boardIdOf);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const batchRemove = useMutation({
    mutationFn: async (ids: string[]) => {
      // 没有批量接口:逐条发、一次性回报。失败的那几条要单独说出来,不能被"已删除 N 项"盖过去。
      const results = await Promise.allSettled(ids.map((id) => deleteBoard(id, workspace.id)));
      return {
        ok: results.filter((result) => result.status === "fulfilled").length,
        failed: results.filter((result) => result.status === "rejected").length,
      };
    },
    onSuccess: ({ ok, failed }) => {
      setBatchDeleting(false);
      refreshList();
      //: 全删掉了就退出选择模式;有失败的就留在模式里 —— 删掉的那些随列表刷新自动不算数
      //: (useMultiSelect 会剔掉),剩下仍勾着的正是没删掉的,可以直接再试一次。
      if (failed) {
        toast.error(t("bulkPartialFailed").replace("{ok}", String(ok)).replace("{failed}", String(failed)));
      } else {
        exit();
        toast.success(t("bulkDeleteDone").replace("{n}", String(ok)));
      }
    },
  });

  if (openSelection.restoring && boards.isPending) {
    return <CanvasDetailLoading testId="boards-detail-restoring" />;
  }

  if (open) {
    return (
      <BoardDetail
        key={open.id}
        board={open}
        workspaceId={workspace.id}
        onBack={() => setOpenId(null)}
        onSaved={() => void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] })}
      />
    );
  }

  // 没有画板时整页只保留一个明确入口。把标题栏和同一个「新建」按钮再留在右上角，
  // 会让空状态的视觉中心下移，也让同一动作出现两遍；工作流空页已经给出了统一模式。
  if (boards.isSuccess && list.length === 0) {
    return (
      <div className={STUDIO_PAGE}>
        <PageHeading title={t("navBoards")} description={t("studioBoardsDesc")} />
        <EmptyState
          icon={<LayoutGrid size={22} />}
          title={t("boardsEmptyTitle")}
          body={t("boardsEmptyHint")}
          action={
            <Button loading={create.isPending} onClick={() => create.mutate()}>
              <Plus size={15} /> {t("boardsNew")}
            </Button>
          }
        />
      </div>
    );
  }

  // 容器、内边距、卡片栅格都跟着工作流列表页走 —— 同一层级的两个页面长得不一样,
  // 用户会以为自己切到了别的应用里。
  return (
    <div className={STUDIO_PAGE}>
      <PageHeading title={t("navBoards")} description={t("studioBoardsDesc")} count={boards.data?.length} actions={
        // 与工作流列表页同一条标题栏:平时是「选择」+「新建」,进了选择模式换成批量动作。
        <span className="flex flex-wrap items-center gap-2">
          {selectMode ? (
            <>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
              </span>
              <Button variant="outline" onClick={() => selectAll(list)}>
                <ListChecks size={13} /> {allSelected(list) ? t("mediaDeselectAll") : t("mediaSelectAll")}
              </Button>
              <Button
                variant="outline"
                className="hover:border-destructive/50 hover:text-destructive"
                disabled={selectedIds.size === 0}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={13} /> {t("delete")}
              </Button>
              <Button variant="outline" onClick={exit}>
                <X size={13} /> {t("cancel")}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" disabled={list.length === 0} onClick={() => setSelectMode(true)}>
                <Check size={13} /> {t("mediaSelectMode")}
              </Button>
              <Button loading={create.isPending} onClick={() => create.mutate()}>
                <Plus size={13} /> {t("boardsNew")}
              </Button>
            </>
          )}
        </span>
      } />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {boards.isLoading ? (
          <div className={CARD_GRID}>
            {[0, 1, 2].map((n) => (
              <CanvasCardSkeleton key={n} />
            ))}
          </div>
        ) : boards.isError ? (
          // 取不到**不是**空的。少了这一支,后端连不上时这页显示的是「创意画板 0」加一个
          // 「新建画板」—— 用户读到的是"我一个画板都没有"。
          <PageLoadError icon={<LayoutGrid size={22} />} error={boards.error} onRetry={() => void boards.refetch()} />
        ) : (
          <div className={CARD_GRID}>
            {list.map((board) => (
              <BoardCard
                key={board.id}
                board={board}
                selecting={selectMode}
                selected={selectedIds.has(board.id)}
                onOpen={() => setOpenId(board.id)}
                onToggle={() => {
                  setSelectMode(true);
                  toggle(board.id);
                }}
                onRename={() => setMenuRenaming(board)}
                onDuplicate={() => duplicate.mutate(board)}
                duplicating={duplicate.isPending && duplicate.variables?.id === board.id}
                onDelete={() => setMenuDeleting(board)}
              />
            ))}
          </div>
        )}
      </div>
      <RenameDialog
        open={menuRenaming !== null}
        title={t("rename")}
        initialValue={menuRenaming?.name ?? ""}
        onCancel={() => setMenuRenaming(null)}
        pending={rename.isPending}
        onSubmit={(name) => {
          if (!menuRenaming) return;
          if (name === menuRenaming.name) setMenuRenaming(null);
          else rename.mutate({ board: menuRenaming, name });
        }}
      />
      <ConfirmDialog
        open={menuDeleting !== null}
        title={t("boardsDeleteTitle")}
        body={menuDeleting?.name}
        onCancel={() => setMenuDeleting(null)}
        pending={remove.isPending}
        onConfirm={() => menuDeleting && remove.mutate(menuDeleting.id)}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("boardsDeleteManyTitle").replace("{n}", String(selectedIds.size))}
        body={t("boardsDeleteManyBody")}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate([...selectedIds])}
      />
    </div>
  );
}

/** useMultiSelect 的 id 取法要是稳定引用 —— 它拿这个函数做依赖,就地写的箭头函数每次渲染都是新的。 */
const boardIdOf = (board: Board) => board.id;

/**
 * 画板卡片。**整张卡**是一个按钮:平时点它打开,选择模式下点它勾选。
 *
 * 单条动作(打开、重命名、创建副本、删除)两个入口、同一份清单:右上角的「⋯」和右键菜单 ——
 * 和工作流、首页、场景的卡片一样。此前卡片上只有一个孤零零的垃圾桶,改名得先点进画板里去。
 * 选择模式下「⋯」收起来,右上角让给勾选圈(批量动作在标题栏上)。
 */
function BoardCard({
  board,
  selecting,
  selected,
  onOpen,
  onToggle,
  onRename,
  onDuplicate,
  duplicating,
  onDelete,
}: {
  board: Board;
  selecting: boolean;
  selected: boolean;
  onOpen: () => void;
  onToggle: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  duplicating: boolean;
  onDelete: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const count = board.canvas?.items?.length ?? 0;
  const marked = selecting && selected;

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div className="group relative min-w-0" data-board-card={board.id}>
          <button
            type="button"
            onClick={selecting ? onToggle : onOpen}
            aria-label={selecting ? `${t("mediaSelectMode")}: ${board.name}` : board.name}
            aria-pressed={selecting ? selected : undefined}
            className="grid w-full gap-3 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {/* 选中态和首页、素材、场景同一个样子:缩略图一圈主色 + 右上角的勾选圈。圈画在缩略图
                **里面**(inset):画在外面的话,最左、最右两列会被滚动容器裁掉一截。 */}
            <span className="relative block">
              <CanvasPreview
                className={marked ? "border-primary ring-1 ring-inset ring-primary" : undefined}
                items={(board.canvas?.items ?? []).map(item => ({ ...item, assetId: item.asset_id, label: item.text || t(({note:"boardsAddNote",image:"kindImage",video:"kindVideo",audio:"kindAudio",frame:"boardsAddFrame",scene:"navScenes",document:"boardKindDocument"} as const)[item.kind]) }))}
                edges={board.canvas?.edges}
              />
              {selecting && <SelectionCheck selected={selected} />}
            </span>
            <span className="truncate pr-8 text-ui-md font-semibold" title={board.name}>{board.name}</span>
            <span className="text-ui-sm text-muted-foreground">{t("boardsItemCount").replace("{n}", String(count))} · {relativeTime(board.updated_at, locale)}</span>
          </button>
          {!selecting && (
            <div className="absolute right-2 top-2 rounded-lg bg-panel">
              <ActionMenu
                label={`${t("studioActions")}: ${board.name}`}
                actions={[
                  { label: t("boardsOpen"), icon: <ArrowUpRight />, onSelect: onOpen },
                  { label: t("rename"), icon: <Pencil />, onSelect: onRename },
                  { label: t("boardsDuplicate"), icon: <Copy />, disabled: duplicating, onSelect: onDuplicate },
                  { label: t("delete"), icon: <Trash2 />, destructive: true, onSelect: onDelete },
                ]}
              />
            </div>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent onCloseAutoFocus={(event) => event.preventDefault()}>
        <ContextMenuItem onSelect={onOpen}>
          <ArrowUpRight /> {t("boardsOpen")}
        </ContextMenuItem>
        <ContextMenuItem onSelect={onRename}>
          <Pencil /> {t("rename")}
        </ContextMenuItem>
        <ContextMenuItem disabled={duplicating} onSelect={onDuplicate}>
          <Copy /> {t("boardsDuplicate")}
        </ContextMenuItem>
        <ContextMenuSeparator />
        {/* 从右键直接进选择模式并勾上这一张 —— 想批量处理时,右键的往往就是第一张。 */}
        <ContextMenuItem onSelect={onToggle}>
          <CheckSquare /> {selecting && selected ? t("boardsDeselect") : t("boardsSelect")}
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          <Trash2 /> {t("delete")}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

function BoardDetail({
  board,
  workspaceId,
  onBack,
  onSaved,
}: {
  board: Board;
  workspaceId: string;
  onBack: () => void;
  onSaved: () => void;
}) {
  const t = useI18n();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [renaming, setRenaming] = React.useState(false);
  const [confirmingDelete, setConfirmingDelete] = React.useState(false);
  const [deletingBoard, setDeletingBoard] = React.useState(false);
  const [collaborationOpen, setCollaborationOpen] = React.useState(false);
  const [commentMode, setCommentMode] = React.useState(false);
  const [markerMode, setMarkerMode] = React.useState(false);
  const [commentsVisible, setCommentsVisible] = React.useState(true);
  const [markersVisible, setMarkersVisible] = React.useState(true);
  const enterMarkerMode = () => { setMarkerMode(true); setMarkersVisible(true); setCommentMode(false); setActiveCommentId(null); };

  const [activeCommentId, setActiveCommentId] = React.useState<string | null>(null);

  //: 画布上的助手。**和工作流那扇是同一个面板** —— 会话池、消息、确认卡都走同一套 agent
  //: session,两边的差别只有附给智能体的那行上下文。各记各的停靠状态和宽度:在画板上
  //: 摊开助手,不该把工作流那边也改了。
  const [agentOpen, setAgentOpen] = usePersistentTab<"on" | "off">("board-agent", "off", ["on", "off"]);
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("board-agent-mode", "docked", ["docked", "floating"]);
  const agentPanel = useResizableSidebar("board-right", { min: 320, max: 640, fallback: 400 });
  const dockedAgent = agentOpen === "on" && agentMode === "docked";
  /*
   * 智能体是**盖在画布上**的,不占版面。全览、跳标记、跳评论都得照"看得见的那块"来算,
   * 否则目标正好落在它底下 —— 用户报过:点「在画布中查看」,评论跳到了智能体那一栏后面。
   * 悬浮时外层 wrapper 是 display:contents(量它拿到空矩形),所以量里面那块面板。
   */
  const agentWrapperRef = React.useRef<HTMLDivElement | null>(null);
  const getCanvasInsets = React.useCallback(
    (surface: HTMLElement) =>
      canvasInsets(surface, dockedAgent ? canvasRightDockOcclusion(agentPanel.width) : 0, [
        agentOpen === "on" && agentMode === "floating" ? agentWrapperRef.current?.firstElementChild : null,
      ]),
    [dockedAgent, agentPanel.width, agentOpen, agentMode],
  );
  //: 全览默认开着 —— 大图时它最有用,而"图大不大"只有用户自己知道。记在本地。
  const [minimapMode, setMinimap] = usePersistentTab<"on" | "off">("board-minimap", "on", ["on", "off"] as const);
  const showMinimap = minimapMode === "on";
  //: 连线走线方式。和工作流同一套开关(components/app/canvasEdgeShape),各记各的偏好 ——
  //: 和全览一样,画板这边的看图习惯不该把工作流那边也改了。
  const [edgeShape, setEdgeShape] = useEdgeShape("board-edge-shape");
  //: 查找节点的命中集,交给画布去画圈。
  const [searchHit, setSearchHit] = React.useState<CanvasSearchHighlight | null>(null);
  const [canvas, setCanvas] = React.useState<Canvas | null>(board.canvas);
  //: 搜的是画布**此刻**的样子(canvas 跟着每次编辑汇上来),刚写的便签马上就能搜到。
  const searchEntries = React.useMemo(
    () => boardSearchEntries((canvas ?? board.canvas)?.items ?? [], t),
    [canvas, board.canvas, t],
  );
  const [picking, setPicking] = React.useState<{ kind: MediaKind; place: (assetId: string) => void } | null>(null);
  //: 3D 场景**先选后放**。后端要求 scene 节点必须带 scene_id(domain/boards/canvas.py),
  //: 所以不能像文档那样先落一个空节点再补 —— 那种节点存不下去。
  const [pickingScene, setPickingScene] = React.useState(false);
  //: 画布交出来的把手。顶栏那组按钮要和身份胶囊并排,而它们依赖画布内部状态。
  //: **类型从画布导出**,别在这儿再抄一份 —— 抄的那份少一个动作不会报错,只会让按钮点了没反应。
  const [api, setApi] = React.useState<BoardCanvasApi | null>(null);
  const commentsKey = ["comments", board.workspace_id, "board", board.id] as const;
  const comments = useQuery({
    queryKey: commentsKey,
    queryFn: () => listComments(board.workspace_id, "board", board.id),
  });
  const members = useQuery({
    queryKey: ["members", board.workspace_id],
    queryFn: () => listMembers(board.workspace_id),
  });
  const createComment = useMutation({
    mutationFn: ({ anchor, draft }: {
      anchor: NonNullable<CollaborationComment["anchor"]>;
      draft: { body: string; bodyDocument: Record<string, unknown>; mentionedUserIds: string[] };
    }) => addComment({
      workspace_id: board.workspace_id,
      subject_type: "board",
      subject_id: board.id,
      body: draft.body,
      body_document: draft.bodyDocument,
      mentioned_user_ids: draft.mentionedUserIds,
      anchor,
    }),
    onSuccess: (comment) => {
      setActiveCommentId(comment.id);
      void queryClient.invalidateQueries({ queryKey: commentsKey });
      void queryClient.invalidateQueries({ queryKey: ["activity", board.workspace_id] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const moveCommentAnchor = useMutation({
    mutationFn: ({ comment, anchor }: {
      comment: CollaborationComment;
      anchor: NonNullable<CollaborationComment["anchor"]>;
    }) => moveComment(comment.id, {
      workspace_id: board.workspace_id,
      anchor,
    }),
    onSuccess: (moved) => {
      queryClient.setQueryData<CollaborationComment[]>(commentsKey, (current) =>
        current?.map((comment) => (comment.id === moved.id ? moved : comment)),
      );
      void queryClient.invalidateQueries({ queryKey: ["activity", board.workspace_id] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const removeComment = useMutation({
    mutationFn: (comment: CollaborationComment) => deleteComment(comment.id, board.workspace_id),
    onSuccess: (_result, comment) => {
      setActiveCommentId((current) => (current === comment.id ? null : current));
      queryClient.setQueryData<CollaborationComment[]>(commentsKey, (current) =>
        current?.filter((item) => item.id !== comment.id),
      );
      void queryClient.invalidateQueries({ queryKey: ["activity", board.workspace_id] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  // Every mutation reads and advances this token. Keeping it in a ref avoids rebuilding callbacks
  // after each autosave while still making the next request depend on the latest server response.
  const revision = React.useRef(board.revision);
  // The token and the projection it describes are one unit. A background refetch must never advance
  // only the token while leaving an older local canvas in place, or that stale canvas could pass CAS.
  const confirmedCanvas = React.useRef<Canvas>(board.canvas);
  const acceptBoard = React.useCallback(
    (fresh: Board) => {
      revision.current = fresh.revision;
      confirmedCanvas.current = fresh.canvas;
      onSaved();
      return fresh;
    },
    [onSaved],
  );
  const recoverConflict = React.useCallback(
    async (error: unknown): Promise<boolean> => {
      if (!(error instanceof ApiError) || error.status !== 409) return false;
      const fresh = await getBoard(board.id, workspaceId);
      revision.current = fresh.revision;
      confirmedCanvas.current = fresh.canvas;
      api?.replace(fresh.canvas);
      setCanvas(fresh.canvas);
      onSaved();
      toast.error(t("boardsCanvasConflict"), { description: t("boardsCanvasConflictDetail") });
      return true;
    },
    [api, board.id, workspaceId, onSaved, t],
  );

  // 提示词面板要让人选模型 —— 两种能力各取一次再合并,和 AI 工作台看到的是同一份。
  const models = useQuery({
    queryKey: ["generation-options", "board"],
    queryFn: async () => {
      const [image, video] = await Promise.all([
        api2<GenerationOption[]>("/api/generation/options?kind=image"),
        api2<GenerationOption[]>("/api/generation/options?kind=video"),
      ]);
      return [...image, ...video];
    },
    staleTime: 60_000,
  });

  /** 系统里拖进来的文件:先传进素材库,再由画布摆到落点上。**只收图片和视频** ——
   *  画板上的项渲染的就是这两种,音频拖进来会变成一个放不了的空框。 */
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const created: { id: string; name: string; kind: "image" | "video" }[] = [];
      for (const file of files) {
        const asset = await importAsset({ workspaceId, file });
        if (asset.kind === "image" || asset.kind === "video") {
          created.push({ id: asset.id, name: asset.name, kind: asset.kind });
        }
      }
      return created;
    },
    onError: (error: Error) => toast.error(error.message),
  });

  /** 在这一格里生成。产出由后端回执填回画布,这里只负责发起 + 轮询到结果为止。 */
  const generate = React.useCallback(
    async (input: {
      kind: "image" | "video";
      prompt: string;
      itemId?: string;
      x?: number;
      y?: number;
      provider?: string;
      providerProfileId?: string;
      model?: string;
      parameters?: Record<string, unknown>;
      sourceAssets?: { asset_id: string; role: string }[];
      form?: BoardItem["form"];
    }) => {
      const itemId = input.itemId ?? `${input.kind}-${Math.random().toString(36).slice(2, 9)}`;
      let placed;
      try {
        placed = await generateOnBoard(board.id, {
          workspace_id: workspaceId,
          base_revision: revision.current,
          item_id: itemId,
          kind: input.kind,
          prompt: input.prompt,
          x: input.x ?? 0,
          y: input.y ?? 0,
          provider: input.provider,
          provider_profile_id: input.providerProfileId,
          model: input.model,
          parameters: input.parameters,
          source_assets: input.sourceAssets,
          form: input.form,
        });
      } catch (error) {
        if (await recoverConflict(error)) return;
        toast.error(t("boardsGenerateFailed"), { description: (error as Error).message });
        return;
      }
      acceptBoard(placed);
      //: **马上把那一格标成「在生成」**。服务端已经摆好占位了,但画布的节点只在挂载时从
      //: canvas 建一次 —— 不主动告诉它的话,节点还是个空槽、面板也不收:用户看到的就是
      //: 「点了没反应」,然后再点一次。
      //: 上一次的报错要一起清掉 —— 重来一次的时候还挂着上次为什么挂,用户会以为这次也挂了。
      const pending = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === itemId);
      const jobId = pending ? itemJobId(pending) : undefined;
      if (jobId) api?.patch(itemId, { form: pending?.form ?? input.form, run: { status: "running", job_id: jobId } });
      setRunning((current) => (current.includes(itemId) ? current : [...current, itemId]));
    },
    [board.id, workspaceId, t, api, acceptBoard, recoverConflict],
  );

  /** 让 AI 往某张便签里写字。同步返回,写完直接把新画布落回本地状态。 */
  const write = React.useCallback(
    async (input: NoteWriteInput) => {
      try {
        const fresh = await runNoteWrite({
          input,
          patch: (itemId, next) => api?.patch(itemId, next),
          request: () =>
            writeOnBoard(board.id, {
              workspace_id: workspaceId,
              base_revision: revision.current,
              item_id: input.itemId,
              prompt: input.prompt,
              provider_profile_id: input.providerProfileId,
              model: input.model,
              source_assets: input.assets,
              context: input.context,
            }),
        });
        acceptBoard(fresh);
      } catch (error) {
        if (await recoverConflict(error)) return;
        toast.error(t("boardWriteFailed"), { description: (error as Error).message });
      }
    },
    [board.id, workspaceId, api, t, acceptBoard, recoverConflict],
  );

  /** 把一段文字念成音频。**异步** —— 和出图出片同一套:摆占位、起任务、轮询等回执填回来。 */
  const speak = React.useCallback(
    async (input: { itemId: string; text: string; voiceId: string; engine: string; engineVoice: string }) => {
      let placed;
      try {
        placed = await speakOnBoard(board.id, {
          workspace_id: workspaceId,
          base_revision: revision.current,
          item_id: input.itemId,
          text: input.text,
          voice_id: input.voiceId,
          engine: input.engine,
          engine_voice: input.engineVoice,
        });
      } catch (error) {
        if (await recoverConflict(error)) return;
        toast.error(t("boardSpeakFailed"), { description: (error as Error).message });
        return;
      }
      acceptBoard(placed);
      //: 和生成那条一样:马上把这一格标成在跑,不然画布上看不出发生了什么。
      const pending = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === input.itemId);
      const jobId = pending ? itemJobId(pending) : undefined;
      if (jobId) api?.patch(input.itemId, { run: { status: "running", job_id: jobId } });
      setRunning((current) => (current.includes(input.itemId) ? current : [...current, input.itemId]));
    },
    [board.id, workspaceId, api, t, acceptBoard, recoverConflict],
  );

  /** 取某一帧,存成一份新素材、落到一个新节点上。**是图片节点** —— 取出来的是一张图。 */
  const grabFrame = React.useCallback(
    async (input: { assetId: string; at: number; x: number; y: number }) => {
      try {
        const made = await grabAssetFrame(input.assetId, input.at);
        //: 直接就有 asset_id —— 取帧是同步的一次 ffmpeg,没有「生成中」这个状态。
        api?.add("image", { asset_id: made.id, x: input.x, y: input.y });
        onSaved();
      } catch (error) {
        toast.error(t("boardGrabFrameFailed"), { description: (error as Error).message });
      }
    },
    [api, onSaved, t],
  );

  /** 截出一段。**产出是一份新素材**,落到一个新节点上 —— 原素材不动。 */
  const trim = React.useCallback(
    async (input: {
      itemId: string;
      assetId: string;
      start: number;
      end: number;
      mute: boolean;
      x: number;
      y: number;
    }) => {
      let placed;
      try {
        placed = await trimOnBoard(board.id, {
          workspace_id: workspaceId,
          base_revision: revision.current,
          item_id: input.itemId,
          asset_id: input.assetId,
          start: input.start,
          end: input.end,
          mute: input.mute,
          x: input.x,
          y: input.y,
        });
      } catch (error) {
        if (await recoverConflict(error)) return;
        toast.error(t("boardTrimFailed"), { description: (error as Error).message });
        return;
      }
      acceptBoard(placed);
      //: **走画布的把手把新那一格加进去。** 回写这里的 canvas 状态是没用的 —— 画布的节点
      //: 只在挂载时从 canvas 建一次(和写文案那条同一个坑)。
      const made = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === input.itemId);
      if (made) api?.add(made.kind, made);
      onSaved();
      setRunning((current) => [...current, input.itemId]);
    },
    [board.id, workspaceId, onSaved, api, t, acceptBoard, recoverConflict],
  );

  //: 还在跑的那几格。**轮询而不是等** —— 生成要几十秒,而用户这期间还在画布上干别的。
  const [running, setRunning] = React.useState<string[]>([]);
  // 重进画板、切走再回来、应用重启都不能丢掉轮询。运行状态住在节点里，因此直接从节点
  // 恢复待观察列表，而不是依赖这个组件一次挂载期内的临时 state。
  React.useEffect(() => {
    const ids = (canvas?.items ?? board.canvas.items).filter(itemIsRunning).map((item) => item.id);
    if (ids.length) setRunning((current) => Array.from(new Set([...current, ...ids])));
  }, [board.id, board.canvas.items, canvas]);
  React.useEffect(() => {
    if (running.length === 0) return;
    const timer = setInterval(async () => {
      const fresh = await getBoard(board.id, workspaceId).catch(() => null);
      if (!fresh) return;
      const local = canvas ?? confirmedCanvas.current;
      const hasLocalChanges = JSON.stringify(local) !== JSON.stringify(confirmedCanvas.current);
      // When the local projection is clean, adopt the complete server projection (including extra
      // multi-image results) and its token together. With local edits pending, show settled states
      // below but keep the old token so the next save correctly conflicts instead of overwriting.
      if (!hasLocalChanges && fresh.revision !== revision.current) {
        revision.current = fresh.revision;
        confirmedCanvas.current = fresh.canvas;
        api?.replace(fresh.canvas);
        setCanvas(fresh.canvas);
      }
      const settled: string[] = [];
      for (const id of running) {
        const item = fresh.canvas.items.find((one) => one.id === id);
        //: 整项没了(比如别处把它删了):没什么可等的了。
        if (!item) {
          settled.push(id);
        } else if (item.asset_id) {
          //: 产出到了:服务端返回 asset_id 与终态 run，整组写回，避免本地继续显示运行中。
          api?.patch(id, boardSettlementPatch(item) ?? {});
          settled.push(id);
        } else if (itemError(item)) {
          //: **跑挂了也要落到画布上。** 此前这里只把 id 从「还在等」的名单里划掉,却没告诉
          //: 画布 —— 而画布的节点只在挂载时从 canvas 建一次,那一格于是会一直保留 running:
          //: 框里持续转圈,底下那个提交按钮也一直按不动。
          api?.patch(id, boardSettlementPatch(item) ?? {});
          settled.push(id);
        }
      }
      if (settled.length) setRunning((current) => current.filter((id) => !settled.includes(id)));
    }, 2500);
    return () => clearInterval(timer);
  }, [running, board.id, workspaceId, api, canvas]);

  /**
   * ⌘/Ctrl+N 打开「添加」弹层 —— 和工作流详情页同键同义(那边是 ⌘N 添加节点)。
   *
   * 做法是点那个按钮而不是把 SearchableSelect 改成受控:它的开合是内部状态,
   * 为一个快捷键改受控,调用它的另外几处都要跟着改(同 WorkflowsView 的取舍)。
   *
   * **在输入框里一律不劫持** —— 在便签/提示词里打字时按 ⌘N,想要的是浏览器的新建窗口
   * (或什么都不发生),而不是画布上冒出一个节点。
   */
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.key.toLowerCase() !== "n") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const trigger = document.querySelector<HTMLButtonElement>("[data-board-add-item]");
      if (!trigger) return;
      event.preventDefault();
      trigger.click();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // 空依赖:这个监听不读任何会变的东西(它用 querySelector 现找那个按钮)。
    // 漏掉依赖数组的话,每次渲染都要拆一次装一次 —— 而画布拖动时那是每帧一次。
  }, []);

  const save = React.useCallback(
    (next: Canvas) => {
      if (JSON.stringify(next) === JSON.stringify(confirmedCanvas.current)) return Promise.resolve();
      return updateBoard(board.id, { workspace_id: workspaceId, base_revision: revision.current, canvas: next })
        .then((fresh) => {
          acceptBoard(fresh);
        })
        // 存不上必须说 —— 画板是攒想法的地方,默默丢掉是最糟的失败方式。
        .catch(async (error: Error) => {
          if (await recoverConflict(error)) throw error;
          toast.error(t("boardsSaveFailed"), { description: error.message });
          // 自动保存只在 Promise 完成后才把这份画布视为已落库。告诉它失败了,
          // 下一次编辑仍会以最后一份真正成功的画布为基准。
          throw error;
        });
    },
    [board.id, workspaceId, t, acceptBoard, recoverConflict],
  );
  // **不显示"已保存"。** 自动保存做对了就该是无声的:一个常驻的「已保存」既不能让人放心
  // (它任何时候都这么写),又占着顶栏一格。失败仍然会 toast —— 那才是需要打断的时刻。
  useAutosave(canvas, save);

  //: 改名走**全站那一个** RenameDialog(设置、首页、会话列表、工作流都走它)。此前这里是
  //: 就地把标题换成一个输入框 —— 少一处确认、少一条校验(空名靠 onBlur 悄悄回滚),
  //: 而"改个名字"在这个应用里已经有答案了,画板没有理由是第九种。
  const [savingName, setSavingName] = React.useState(false);
  const rename = (next: string) => {
    if (next === board.name) {
      setRenaming(false);
      return;
    }
    // 存完再关:进行中确认键转圈(见 RenameDialog 的 pending)。
    setSavingName(true);
    updateBoard(board.id, { workspace_id: workspaceId, base_revision: revision.current, name: next })
      .then((fresh) => {
        acceptBoard(fresh);
        setRenaming(false);
      })
      .catch(async (error: Error) => {
        if (!(await recoverConflict(error))) toast.error(error.message);
      })
      .finally(() => setSavingName(false));
  };

  // 版式跟着工作流详情页:**画布铺满,两组胶囊浮在上面** —— 左边是身份(回哪儿去、这是谁),
  // 右边是操作。悬浮不等于没有边界:两组各有自己的底,否则它们会散在画布上和内容抢注意力。
  return (
    <div className="relative grid h-full min-h-0">
      <div className="pointer-events-none absolute inset-x-2 top-2 z-20 flex items-start justify-between gap-2 [&>*]:pointer-events-auto">
        {/* 和工作流详情页、子图共用同一颗胶囊(components/app/canvasTitle)—— 它们是同一类
            东西:「你现在在哪儿」。此前这里是自己写的一份,标题的 font-semibold 挂在 <button>
            上,被 tokens.css 那条无层级的 `button { font: inherit }` 压掉了,于是画板的标题
            比工作流的明显更细 —— 而两处的 class 写得一模一样。 */}
        <CanvasTitle
          onBack={onBack}
          backLabel={t("navBoards")}
          name={board.name}
          onRename={() => setRenaming(true)}
          renameLabel={t("rename")}
        />


        <CanvasToolbar
          label={t("canvasTools")}
          data-board-toolbar-actions=""
          end={
            <>
              <CanvasToolbarGroup label={t("wfAgentTitle")}>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className={cn(agentOpen === "on" && "bg-secondary text-foreground")}
                  title={t("wfAgentTitle")}
                  aria-label={t("wfAgentTitle")}
                  aria-pressed={agentOpen === "on"}
                  onClick={() => setAgentOpen(agentOpen === "on" ? "off" : "on")}
                >
                  <Bot size={14} />
                </Button>
              </CanvasToolbarGroup>
              <CanvasToolbarGroup label={t("more")}>
                <ActionMenu
                  label={t("more")}
                  actions={[
                    {
                      label: t("delete"),
                      icon: <Trash2 size={14} />,
                      destructive: true,
                      onSelect: () => setConfirmingDelete(true),
                    },
                  ]}
                />
              </CanvasToolbarGroup>
            </>
          }
        >
          <CanvasToolbarGroup label={t("canvasEditTools")}>
            <SearchableSelect
              value=""
              onValueChange={(kind) => {
                setMarkerMode(false);
                setCommentMode(false);
                setActiveCommentId(null);
                //: `pick-<kind>` 一条分支通吃三类。此前只认死 "pick-image",于是新增视频/音频
                //: 就得再抄两遍同样的三行 —— 而 AssetPickerDialog 本来就是按 kind 列的。
                if (kind.startsWith("pick-")) {
                  const media = kind.slice("pick-".length) as MediaKind;
                  setPicking({ kind: media, place: (assetId) => api?.add(media, { asset_id: assetId }) });
                } else if (kind === "scene") {
                  setPickingScene(true);
                } else {
                  api?.add(kind as "note" | "image" | "video" | "audio" | "frame" | "document");
                }
              }}
              searchPlaceholder={t("boardsAddItem")}
              options={[
                //: **同一组的选项必须挨在一起。** SearchableSelect 按*相邻*的同名 group 归组
                //: (它不重排,理由见那边的注释),所以隔开写就会渲染出第二个同名小标题 ——
                //: 「选一张图片」此前排在最末,菜单里于是有两个「素材库」。
                { value: "document", label: t("boardKindDocument"), group: t("boardsGroupAssets") },
                { value: "scene", label: t("navScenes"), group: t("boardsGroupAssets") },
                { value: "pick-image", label: t("boardsPickImage"), group: t("boardsGroupAssets") },
                { value: "pick-video", label: t("boardsPickVideo"), group: t("boardsGroupAssets") },
                { value: "pick-audio", label: t("boardsPickAudio"), group: t("boardsGroupAssets") },
                { value: "note", label: t("boardsAddNote"), group: t("boardsGroupCreate") },
                { value: "image", label: t("boardsAddImage"), group: t("boardsGroupCreate") },
                { value: "video", label: t("boardsAddVideo"), group: t("boardsGroupCreate") },
                { value: "audio", label: t("boardsAddAudio"), group: t("boardsGroupCreate") },
                { value: "frame", label: t("boardsAddFrame"), group: t("boardsGroupCreate") },
              ]}
              trigger={
                <button
                  type="button"
                  data-board-add-item=""
                  className="inline-flex h-8 items-center gap-2 rounded-md bg-action px-3 text-action-foreground hover:bg-action/90"
                  aria-label={t("boardsAddItem")}
                  title={`${t("boardsAddItem")} ⌘N`}
                >
                  <Plus size={15} /> {t("boardsAddItem")}
                </button>
              }
            />
            <Button
              variant="ghost"
              size="icon-sm"
              title={`${t("undo")}  ⌘Z`}
              aria-label={t("undo")}
              disabled={!api?.canUndo}
              onClick={() => api?.undo()}
            >
              <Undo2 size={14} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              title={`${t("redo")}  ⌘⇧Z`}
              aria-label={t("redo")}
              disabled={!api?.canRedo}
              onClick={() => api?.redo()}
            >
              <Redo2 size={14} />
            </Button>
          </CanvasToolbarGroup>
          <CanvasToolbarGroup label={t("boardCommentMode")}>
            <AnnotationControls
              kind="comment"
              active={commentMode}
              visible={commentsVisible}
              onMode={() => {
                setCommentMode(!commentMode);
                setActiveCommentId(null);
                setMarkerMode(false);
                setCommentsVisible(true);
              }}
              onVisible={() => {
                setCommentsVisible(!commentsVisible);
                setActiveCommentId(null);
                if (commentsVisible) setCommentMode(false);
              }}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              title={t("boardDiscussionCenter")}
              aria-label={t("boardDiscussionCenter")}
              onClick={() => setCollaborationOpen(true)}
            >
              <ListChecks size={14} />
            </Button>
          </CanvasToolbarGroup>
          <CanvasToolbarGroup label={t("markers")}>
            <AnnotationControls
              kind="marker"
              active={markerMode}
              visible={markersVisible}
              onMode={() => (markerMode ? setMarkerMode(false) : enterMarkerMode())}
              onVisible={() => {
                setMarkersVisible(!markersVisible);
                if (markersVisible) setMarkerMode(false);
              }}
            />
            <MarkerListButton
              markers={api?.markers ?? []}
              onJump={(marker) => {
                setMarkersVisible(true);
                api?.jumpToMarker(marker);
              }}
            />
          </CanvasToolbarGroup>
          <CanvasToolbarGroup label={t("canvasViewTools")}>
            <CanvasNodeSearch
              entries={searchEntries}
              placeholder="boardSearchPlaceholder"
              onFocus={(itemId) => api?.focusItem(itemId)}
              onHighlight={setSearchHit}
            />
            <EdgeShapeToggle value={edgeShape} onChange={setEdgeShape} />
            <CanvasInputModeSwitch />
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn(showMinimap && "bg-secondary text-foreground")}
              title={t("wfMinimap")}
              aria-label={t("wfMinimap")}
              aria-pressed={showMinimap}
              onClick={() => setMinimap(showMinimap ? "off" : "on")}
            >
              <MapIcon size={14} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              title={t("boardsFitView")}
              aria-label={t("boardsFitView")}
              onClick={() => api?.fitView()}
            >
              <Maximize2 size={14} />
            </Button>
          </CanvasToolbarGroup>
        </CanvasToolbar>
      </div>

      {agentOpen === "on" && (
        // 停靠时与满铺画布四周保持标准内缩,从工具条底下起(和工作流详情页同一套刻度)。
        // 悬浮时 wrapper 必须是 display:contents:助手自身已经 fixed 脱离文档流；若这个空 wrapper
        // 仍作为 grid item，根网格会凭空多出一行，把 React Flow 压到页面下半截。
        <div
          ref={agentWrapperRef}
          className={dockedAgent ? "absolute z-10 grid min-h-0 min-w-0" : "contents"}
          style={dockedAgent ? {
            width: agentPanel.width,
            ...canvasDockedPanelEdges(8),
          } : undefined}
        >
          <CanvasAgentChat
            contextLine={t("boardAgentContext").replace("{id}", board.id).replace("{name}", board.name)}
            emptyHint={t("boardAgentEmpty")}
            placeholder={t("boardAgentPlaceholder")}
            rectKey="mosael.board.agent.rect.v1"
            workspaceId={workspaceId}
            mode={agentMode}
            onModeChange={setAgentMode}
            onClose={() => setAgentOpen("off")}
          />
        </div>
      )}
      {dockedAgent && (
        <RightDockResizeHandle panel={agentPanel} toolbarTop={8} />
      )}

      <BoardCanvas
        boardId={board.id}
        workspaceId={workspaceId}
        canvas={board.canvas ?? { items: [], edges: [] }}
        getInsets={getCanvasInsets}
        onChange={setCanvas}
        onPickAsset={(kind, place) => setPicking({ kind, place })}
        onGenerate={generate}
        onWrite={write}
        onSpeak={speak}
        onTrim={trim}
        onGrabFrame={grabFrame}
        models={models.data ?? []}
        showMinimap={showMinimap}
        edgeShape={edgeShape}
        searchHighlight={searchHit}
        onDropFiles={(files) => upload.mutateAsync(files)}
        uploading={upload.isPending}
        commentMode={commentMode}
        markerMode={markerMode}
        markersVisible={markersVisible}
        commentsVisible={commentsVisible}
        comments={comments.data ?? []}
        members={members.data?.members ?? []}
        currentUserId={user?.id ?? null}
        activeCommentId={activeCommentId}
        onSelectComment={(comment) => setActiveCommentId(comment?.id ?? null)}
        onCreateComment={(anchor, draft) => createComment.mutateAsync({
          anchor,
          draft: {
            body: draft.body,
            bodyDocument: draft.bodyDocument as Record<string, unknown>,
            mentionedUserIds: draft.mentionedUserIds,
          },
        })}
        onMoveComment={(comment, anchor) => moveCommentAnchor.mutateAsync({ comment, anchor })}
        onDeleteComment={(comment) => removeComment.mutateAsync(comment)}
        onExitCommentMode={() => { setCommentMode(false); setActiveCommentId(null); }}
        onExitMarkerMode={() => setMarkerMode(false)}
        onReady={setApi}
      />

      <RenameDialog
        open={renaming}
        title={t("rename")}
        initialValue={board.name}
        onCancel={() => setRenaming(false)}
        pending={savingName}
        onSubmit={rename}
      />

      <CollaborationSheet
        open={collaborationOpen}
        onOpenChange={setCollaborationOpen}
        workspaceId={board.workspace_id}
        subjectType="board"
        subjectId={board.id}
        onJumpToComment={(comment) => {
          setCommentMode(true);
          setCommentsVisible(true);
          setMarkerMode(false);
          setActiveCommentId(comment.id);
          setCollaborationOpen(false);
          requestAnimationFrame(() => api?.focusComment(comment));
        }}
      />

      <ConfirmDialog
        open={confirmingDelete}
        title={t("boardsDeleteTitle")}
        body={board.name}
        onCancel={() => setConfirmingDelete(false)}
        pending={deletingBoard}
        onConfirm={() => {
          setDeletingBoard(true);
          void deleteBoard(board.id, workspaceId)
            .then(() => {
              setConfirmingDelete(false);
              onSaved();
              onBack();
            })
            .catch((error: Error) => toast.error(error.message))
            .finally(() => setDeletingBoard(false));
        }}
      />

      {workspaceId && (

        <ScenePickerDialog

          workspaceId={workspaceId}

          open={pickingScene}

          onOpenChange={setPickingScene}

          onPick={(scene) => api?.add("scene", { scene_id: scene.id, text: scene.name })}

        />

      )}

      <AssetPickerDialog
        open={picking !== null}
        kind={picking?.kind ?? "image"}
        workspaceId={workspaceId}
        onOpenChange={(next) => !next && setPicking(null)}
        onPick={(assetId) => {
          picking?.place(assetId);
          setPicking(null);
        }}
      />
    </div>
  );
}
