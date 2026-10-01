import { CanvasToolbar, CanvasToolbarGroup } from "@/components/app/CanvasToolbar";
import { ActionMenu } from "@/components/app/ActionMenu";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import React from "react";
import { useOpenRequest } from "@/lib/deepLink";
import { CARD_GRID, PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { CanvasPreview } from "@/components/layout/CanvasPreview";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Check, CheckSquare, Copy, LayoutGrid, ListChecks, Map as MapIcon, Maximize2, Pencil, Plus, Redo2, Trash2, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { errorText } from "@/api/errorMessage";

import {
  ApiError,
  cancelJob,
  createBoard,
  createBoardSequence,
  isNodeProducer,
  listBoardProducers,
  deleteBoard,
  duplicateBoard,
  grabAssetFrame,
  runOnBoard,
  getBoard,
  importAsset,
  addComment,
  deleteComment,
  moveComment,
  listComments,
  listMembers,
  listBoards,
  updateBoard,
  type Board,
  type BoardItem,
  type BoardSummary,
  type BoardCanvas as Canvas,
  type BuiltinProducer,
  type BoardRunRequest,
  type Workspace,
  type CollaborationComment,
} from "@/api/client";
import { useAuth } from "@/app/auth";
import { itemName, type MediaKind } from "@/features/boards/boardNodes";
import { assetFields, placedAsset, type PlacedAsset } from "@/features/boards/boardPlacement";
import { boardAddCatalog, SCENE_FROM_TEXT } from "@/features/boards/boardTools";
import { useI18n, usePreferences } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { usePageTrail } from "@/components/layout/pageTrail";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { CanvasDetailLoading } from "@/components/layout/CanvasDetailLoading";
import { CanvasCardSkeleton } from "@/components/layout/CanvasCardSkeleton";
import { useGenerationOptions } from "@/lib/generationOptions";
import { relativeTime } from "@/lib/time";
import { usePersistentSelection, usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { listenKeys } from "@/lib/shortcuts";
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
import { EntityPickerDialog } from "@/features/entities/EntityPickerDialog";
import { announceEntityReceipt } from "@/features/entities/entityMeta";
import { boardSettlementPatch, itemIsRunning, prunedLinksPatch, serverOwnedPatch } from "@/features/boards/boardItemState";
import { rebaseCanvas } from "@/features/boards/boardRebase";
import { sequencesFilledFrom } from "@/features/boards/useBoardSequenceLinks";
import { boardSequenceKey } from "@/features/boards/SequenceCell";
import { createWriteQueue, sameContent } from "@/lib/optimisticWrites";
import { importEach, importFailureText } from "@/lib/importEach";
import { assetKeys, boardKeys } from "@/api/queryKeys";
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
    queryKey: boardKeys.list(workspace.id),
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

  const refreshList = () => void queryClient.invalidateQueries({ queryKey: boardKeys.list(workspace.id), exact: true });

  //: 卡片上的单条动作(「⋯」菜单与右键菜单共用):打开、重命名、创建副本、删除。
  const [menuRenaming, setMenuRenaming] = React.useState<BoardSummary | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<BoardSummary | null>(null);
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
    mutationFn: ({ board, name }: { board: BoardSummary; name: string }) =>
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
    mutationFn: (board: BoardSummary) =>
      duplicateBoard(board.id, { workspace_id: workspace.id, name: t("boardsCopyName").replace("{name}", board.name) }),
    onSuccess: (made) => {
      refreshList();
      toast.success(t("boardsDuplicated").replace("{name}", made.name));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // 多选与首页、素材、工作流同一份状态机(见 lib/useMultiSelect):退出即清空、被删掉的自动剔除。
  const { selectMode, enter: enterSelectMode, selectedIds, toggle, selectAll, allSelected, exit } = useMultiSelect(list, boardIdOf);
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
      <OpenBoard
        key={open.id}
        boardId={open.id}
        workspaceId={workspace.id}
        onBack={() => {
          setOpenId(null);
          //: 回到清单时再取一遍摘要(缩略图):打开着的时候只改了清单里这一张的版本号和时间,没重取。
          refreshList();
        }}
        //: **只改清单里这一张**(名字、版本号、「最近编辑」、格子数)—— 不重取整张清单:打开着一张板时每存一次都会走到这。
        //: 版本号要跟上:清单上的「重命名」带着它去比较并交换。
        onSaved={(fresh) =>
          queryClient.setQueryData<BoardSummary[]>(boardKeys.list(workspace.id), (current) =>
            current?.map((one) =>
              one.id === fresh.id
                ? { ...one, name: fresh.name, revision: fresh.revision, updated_at: fresh.updated_at, item_count: fresh.canvas.items.length }
                : one,
            ),
          )
        }
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
              <Button variant="outline" disabled={list.length === 0} onClick={() => enterSelectMode()}>
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
                  enterSelectMode();
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
const boardIdOf = (board: BoardSummary) => board.id;

/**
 * 打开的那一张:清单只有摘要,整份画布从详情接口取,取到了才挂画布(画布的节点、版本号、撤销历史都只在挂上
 * 那一刻从这一份建一次)。之后这份缓存由画布自己写回的每一版更新(见 BoardDetail 的 acceptBoard / adoptServer)。
 */
function OpenBoard({
  boardId,
  workspaceId,
  onBack,
  onSaved,
}: {
  boardId: string;
  workspaceId: string;
  onBack: () => void;
  onSaved: (fresh: Board) => void;
}) {
  const detail = useQuery({
    queryKey: boardKeys.detail(workspaceId, boardId),
    queryFn: () => getBoard(boardId, workspaceId),
    staleTime: Infinity,
  });
  if (detail.isPending) return <CanvasDetailLoading testId="boards-detail-loading" />;
  if (detail.isError) {
    return <PageLoadError icon={<LayoutGrid size={22} />} error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  return <BoardDetail board={detail.data} workspaceId={workspaceId} onBack={onBack} onSaved={onSaved} />;
}

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
  board: BoardSummary;
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
  const count = board.item_count;
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
                //: 缩略图上每一格写一行字:起了名写名字,没起名写正文(便签那句话、文档标题),都没有写种类名。
                items={board.preview.items.map((item) => ({
                  ...item,
                  width: item.width ?? undefined,
                  height: item.height ?? undefined,
                  assetId: item.asset_id ?? undefined,
                  label: item.title?.trim() || item.text || itemName(t, item as Pick<BoardItem, "kind" | "title">),
                }))}
                edges={board.preview.edges}
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

/** 保存被拒时服务端点名的那一格(回包里的 `item_id`,见后端 routes/boards.update);没点名回 null。 */
function failedItem(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 400) return null;
  try {
    const itemId = (JSON.parse(error.body) as { item_id?: unknown }).item_id;
    return typeof itemId === "string" && itemId ? itemId : null;
  } catch {
    return null;
  }
}

/** 某个产出者没跑起来时那句提示。按产出者说 —— 「生成失败」挂在一次写字上是错话。 */
const RUN_FAILED: Record<BuiltinProducer, MessageKey> = {
  generate: "boardsGenerateFailed",
  write: "boardWriteFailed",
  speak: "boardSpeakFailed",
  trim: "boardTrimFailed",
  scene_render: "boardSceneRenderFailed",
  sequence_export: "boardSequenceExportFailed",
};

function BoardDetail({
  board,
  workspaceId,
  onBack,
  onSaved,
}: {
  board: Board;
  workspaceId: string;
  onBack: () => void;
  /** 这张板有了服务端的新一版(自己存的、合进来的):清单里这一张跟着改。 */
  onSaved: (fresh: Board) => void;
}) {
  const t = useI18n();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [renaming, setRenaming] = React.useState(false);
  //: 顶栏的路径:创意画板 / 这张板(点名字改名,点「创意画板」回清单)。
  usePageTrail({ onRoot: onBack, segments: [{ label: board.name, onRename: () => setRenaming(true), renameLabel: t("rename") }] });
  const [confirmingDelete, setConfirmingDelete] = React.useState(false);
  const [deletingBoard, setDeletingBoard] = React.useState(false);
  const [collaborationOpen, setCollaborationOpen] = React.useState(false);
  const [commentMode, setCommentMode] = React.useState(false);
  const [markerMode, setMarkerMode] = React.useState(false);
  const [commentsVisible, setCommentsVisible] = React.useState(true);
  const [markersVisible, setMarkersVisible] = React.useState(true);
  const enterMarkerMode = () => { setMarkerMode(true); setMarkersVisible(true); setCommentMode(false); setActiveCommentId(null); };
  //: 跳到一枚标记时先显示标记(画布的 jumpToMarker 调它;清单和快捷键同一条)。稳定引用:它在画布把手的依赖里。
  const revealMarkers = React.useCallback(() => setMarkersVisible(true), []);

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
  //: 本地那份画布的最新值,给定时器和动作的回调读。**不进定时器的依赖**:进了的话每拖一下轮询
  //: 就重来一次,一直在拖就一直轮询不到 —— 产出要等人停手 2.5 秒之后才出现。
  const localCanvas = React.useRef(canvas);
  localCanvas.current = canvas;
  //: 搜的是画布**此刻**的样子(canvas 跟着每次编辑汇上来),刚写的便签马上就能搜到。
  const searchEntries = React.useMemo(
    () => boardSearchEntries((canvas ?? board.canvas)?.items ?? [], t),
    [canvas, board.canvas, t],
  );
  //: 挑一份素材:给一格换一份(只列那一类),或「添加 → 素材」(三种都列,挑中哪种放哪种格子)。
  const [picking, setPicking] = React.useState<{
    kind: MediaKind | "media";
    place: (asset: PlacedAsset) => void;
    /** 连文档一起列(「从库里放」:文档落成一格文档格)。 */
    withDocuments?: boolean;
    /** 这张画板上已有的素材(时间线格的「+」):选择器里多一枚「这张画板上的」。 */
    onBoard?: string[];
  } | null>(null);
  //: 3D 场景**先选后放**。后端要求 scene 节点必须带 scene_id(domain/boards/canvas.py),
  //: 所以不能像文档那样先落一个空节点再补 —— 那种节点存不下去。
  const [pickingScene, setPickingScene] = React.useState(false);
  const [pickingEntity, setPickingEntity] = React.useState(false);
  //: 画布交出来的把手。顶栏那组按钮要和身份胶囊并排,而它们依赖画布内部状态。
  //: **类型从画布导出**,别在这儿再抄一份 —— 抄的那份少一个动作不会报错,只会让按钮点了没反应。
  const [api, setApi] = React.useState<BoardCanvasApi | null>(null);
  //: 画布的把手的最新一份,给卸载、关页面、定时器读。
  const apiRef = React.useRef(api);
  apiRef.current = api;
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
  //: 这张板上的写请求(自动保存、改名、生成、写字、念、截)排成一队,各自轮到时才读版本号 ——
  //: 见 lib/optimisticWrites.createWriteQueue。
  const [serially] = React.useState(createWriteQueue);
  //: 这张板的详情缓存(OpenBoard 取的那一份,`board` 就是它):自己写回来的每一版放进去;别处让它作废(任务做完、
  //: 智能体改板批准之后)时重取,比手上的新就合进本地(见下面采用它的那个 effect)。
  const detailKey = React.useMemo(() => boardKeys.detail(workspaceId, board.id), [workspaceId, board.id]);
  const acceptBoard = React.useCallback(
    (fresh: Board) => {
      revision.current = fresh.revision;
      confirmedCanvas.current = fresh.canvas;
      queryClient.setQueryData(detailKey, fresh);
      onSaved(fresh);
      return fresh;
    },
    [onSaved, queryClient, detailKey],
  );
  /**
   * 采用服务端更新的一版:本地没存上的改动按格子重放到它上面(boardRebase),撤销历史照留(画布的 adopt)。
   *
   * 服务端那一版前进了,原因多半是服务端自己写的一格 —— 生成的占位、回执落下的产出 —— 或智能体改板批准后
   * 的那一步,不是「别处」。此前本地一有没存的改动就不采用,下一次保存必撞 409,撞了就把本地整份换掉:刚拖的、
   * 刚敲的一起没了。合好的那份交给自动保存,带着新的版本号存回去。
   *
   * 回「有没有两边改了同一格同一字段」—— 有才值得打断人说一声。不比当前新的(比如保存已经把版本推过去了)不采用。
   */
  /**
   * 服务端刚落下的格子(一项能力的产出、一次多张的其余几张)**全在视野外**时说一声,带一个「去看看」。
   * 不自己把视野挪过去:人这会儿可能正在别处干活,落下一格就被拽走比看不见更糟。
   */
  //: 文案函数经 ref 读:这个回调在 adoptServer 的依赖里,而 adoptServer 在轮询定时器的依赖里 —— 它一换,定时器就重来。
  const tRef = React.useRef(t);
  tRef.current = t;
  const announceOffscreen = React.useCallback(
    (base: Canvas, merged: Canvas, fresh: Canvas) => {
      const t = tRef.current;
      const known = new Set([...base.items, ...(localCanvas.current?.items ?? [])].map((item) => item.id));
      const landed = fresh.items.filter((item) => !known.has(item.id) && merged.items.some((one) => one.id === item.id));
      if (landed.length === 0 || !api) return;
      const rect = (item: BoardItem) => ({ x: item.x, y: item.y, width: item.width ?? 200, height: item.height ?? 120 });
      if (landed.some((item) => api.isInView(rect(item)))) return;
      toast.success(t("boardOutputsOffscreen").replace("{n}", String(landed.length)), {
        action: { label: t("boardShowOutputs"), onClick: () => api.focusItem(landed[0].id) },
      });
    },
    [api],
  );
  const adoptServer = React.useCallback(
    (fresh: Board): { adopted: boolean; conflicted: boolean } => {
      if (fresh.revision <= revision.current) return { adopted: false, conflicted: false };
      const base = confirmedCanvas.current;
      //: 「本地」是画布**此刻**的样子,不是上一次汇上来的那份:画布的变化攒到停手 400ms 才汇(useBoardHistory),
      //: 窗口里刚敲的字、刚按的 ⌘Z 只在画布上。拿汇上来的那份去合,装回画布时就把它们冲掉了。先 flush 拿现在这一份
      //: (它也同时汇上来、记进撤销);flush 和下面装回去在同一段同步代码里,中间插不进新的编辑。
      const mine = api?.flush() ?? localCanvas.current ?? base;
      const { canvas: merged, conflicted } = rebaseCanvas(base, mine, fresh.canvas);
      revision.current = fresh.revision;
      confirmedCanvas.current = fresh.canvas;
      queryClient.setQueryData(detailKey, fresh);
      //: 产出刚落进连着时间线格的那一格:服务端已经把它接到时间线末尾,格子读的那条跟着刷新。
      for (const sequenceId of sequencesFilledFrom(base, fresh.canvas)) {
        void queryClient.invalidateQueries({ queryKey: boardSequenceKey(sequenceId) });
      }
      api?.adopt(merged, (snapshot) => rebaseCanvas(base, snapshot, fresh.canvas).canvas);
      announceOffscreen(base, merged, fresh.canvas);
      localCanvas.current = merged;
      setCanvas(merged);
      onSaved(fresh);
      return { adopted: true, conflicted };
    },
    [api, onSaved, queryClient, detailKey, announceOffscreen],
  );
  //: 详情缓存里来了更新的一版(智能体改板批准之后、任务做完之后的重取):排进写队列合进本地。
  //: 在路上的保存先回来把版本推过去的话,这一份就不比手上的新,adoptServer 不采用。
  const latest = board;
  React.useEffect(() => {
    if (!api || latest.revision <= revision.current) return;
    void serially(async () => {
      adoptServer(latest);
    });
  }, [api, latest, adoptServer, serially]);
  const recoverConflict = React.useCallback(
    async (error: unknown): Promise<boolean> => {
      if (!(error instanceof ApiError) || error.status !== 409) return false;
      const { conflicted } = adoptServer(await getBoard(board.id, workspaceId));
      if (conflicted) toast.error(t("boardsCanvasConflict"), { description: t("boardsCanvasConflictDetail") });
      return true;
    },
    [adoptServer, board.id, workspaceId, t],
  );

  //: 这个人在画板上能用的产出者:一格的能力(操作条上那一排和它们的面板)、空槽的产出者切换都照它。
  const producers = useQuery({
    queryKey: ["board-producers", workspaceId],
    queryFn: () => listBoardProducers(workspaceId),
    staleTime: 30_000,
  });
  //: 生成能挂在哪几种格子上,由后端说(generate 的 hosts 来自生成目录)—— 目录多认一种(音频),
  //: 这里就多取一种的模型,不在前端写死 image / video。
  const generationKinds = producers.data?.find((one) => one.id === "generate")?.hosts;

  // 提示词面板要让人选模型 —— 每种能力各取一次再合并,和 AI 工作台看到的是同一份。
  const models = useGenerationOptions(generationKinds ?? [], { enabled: Boolean(generationKinds) });

  //: 工具条「添加」的整张单子:只有格子,按动词分成生成 / 从素材库 / 引用 / 整理(见 boardTools.boardAddCatalog)。
  //: 没有「工具」一组 —— 把内容变成新内容的事是格子自己的能力,选中一格在操作条上点。每一行都是图标、名字、
  //: 一句说明;图标就是那种格子的图标(画布上、拉线菜单里是同一颗)。
  const addOptions = React.useMemo(
    () => boardAddCatalog(t).map(({ icon: Icon, ...one }) => ({ ...one, icon: <Icon /> })),
    [t],
  );

  /** 系统里拖进来 / 粘贴进来的文件:先传进素材库,再由画布按种类各放一格(图片、视频、音频都有自己的格子,
   *  见 boardPlacement.assetItem;文档落成一格文档格)。哪些种类放得上画板由 boardPlacement.placedAsset 判。
   *  **一个失败不拦后面的**(lib/importEach,和素材库的导入同一条):进了库的照样上画板、素材库照样刷新,
   *  没进来的最后一并说。 */
  const upload = useMutation({
    mutationFn: (files: File[]) => importEach(files, (file) => importAsset({ workspaceId, file })),
    onSuccess: ({ imported, failed }) => {
      if (imported.length) void queryClient.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      const partial = importFailureText(t, imported.length, failed);
      if (partial) toast.error(partial);
    },
  });
  const uploadFiles = upload.mutateAsync;
  const importFiles = React.useCallback(
    async (files: File[]): Promise<PlacedAsset[]> => {
      const { imported } = await uploadFiles(files);
      return imported.map(placedAsset).filter((one): one is PlacedAsset => one !== null);
    },
    [uploadFiles],
  );

  const save = React.useCallback(
    (latest: Canvas) => {
      //: 这一份是在哪个底子上改出来的。排队期间服务端那一版可能被采用了(轮询、别的写请求撞了版本号):
      //: 轮到它时底子变了,就把它的改动重放到新的底子上再发 —— 原样发的话,它会把刚采用的那几格(回执落下的
      //: 产出、派生出来的几格)当成「本地删掉的」存没。
      const base = confirmedCanvas.current;
      return serially(async () => {
        const next = confirmedCanvas.current === base ? latest : rebaseCanvas(base, latest, confirmedCanvas.current).canvas;
        //: 轮到它时再比、再读版本号:排在它前面的写请求可能刚把画布推进到这一份。
        if (sameContent(next, confirmedCanvas.current)) return;
        const fresh = acceptBoard(await updateBoard(board.id, { workspace_id: workspaceId, base_revision: revision.current, canvas: next }));
        //: 服务端没收下的运行态/产出,本地跟着回来(见 serverOwnedPatch);服务端摘掉的、线已经
        //: 断了的槽位素材,本地也跟着摘(见 prunedLinksPatch)。
        const sent = new Map(next.items.map((item) => [item.id, item]));
        const local = new Map((localCanvas.current?.items ?? []).map((item) => [item.id, item]));
        for (const stored of fresh.canvas.items) {
          const mine = sent.get(stored.id);
          if (!mine) continue;
          const patch = {
            ...serverOwnedPatch(mine, stored),
            ...prunedLinksPatch(mine, stored, local.get(stored.id) ?? mine),
          };
          if (Object.keys(patch).length) api?.patch(stored.id, patch);
        }
      })
        // 存不上必须说 —— 画板是攒想法的地方,默默丢掉是最糟的失败方式。
        .catch(async (error: Error) => {
          //: 撞了版本号:合好的那份已经交给自动保存(adoptServer 里的 setCanvas),它接着带新版本号存。
          if (await recoverConflict(error)) throw error;
          //: 存不下是因为某一格(字太长、字段写错):服务端说了是哪一格,跳过去、圈出来 —— 报错那句话里的 id 是内部的,
          //: 人认不出是哪张便签。
          const culprit = failedItem(error);
          if (culprit && localCanvas.current?.items.some((one) => one.id === culprit)) {
            api?.focusItem(culprit);
            setSearchHit({ ids: new Set([culprit]), activeId: culprit });
            toast.error(t("boardSaveFailedAt"), { description: error.message });
          } else {
            toast.error(t("boardsSaveFailed"), { description: error.message });
          }
          // 自动保存只在 Promise 完成后才把这份画布视为已落库。告诉它失败了,
          // 下一次编辑仍会以最后一份真正成功的画布为基准。
          throw error;
        });
    },
    [board.id, workspaceId, t, api, acceptBoard, recoverConflict, serially],
  );
  // **不显示"已保存"。** 自动保存做对了就该是无声的:一个常驻的「已保存」既不能让人放心
  // (它任何时候都这么写),又占着顶栏一格。失败仍然会 toast —— 那才是需要打断的时刻。
  /**
   * `flushSaves`:画布上的动作(生成、写字、念、截)发出去之前,**先把没存的编辑送到服务端**。
   *
   * 服务端照着它那份画布去做 —— 写字读的是便签上现在的字。自动保存要等 600ms 防抖,用户刚敲完
   * 字就点「改写」,服务端读到的还是上一版,改写的对象不是他眼前那一段。存不上时(已经提示过了)
   * 动作就不发。
   */
  //: `latest`:离开画板、关页面时,画布还攒着没汇上来的那一下(并步窗口)也得存上 —— 卸载时这里的清理比画布的先跑。
  const { flush: flushSaves } = useAutosave(canvas, save, { latest: () => apiRef.current?.flush() });
  //: 画布汇上来的新一份。本地那份的引用**当场**换上:动作(生成、写字)和轮询读的是它,不等下一次渲染。
  const onCanvasChange = React.useCallback((next: Canvas) => {
    localCanvas.current = next;
    setCanvas(next);
  }, []);

  /**
   * 在画板上跑一次产出者(生成、写字、念出来、截一段)。**画布上的一切产出都从这里发** —— 走同一条
   * runOnBoard,后端按 `producer` 分给注册表里那一个(见后端 boards/producers.py)。
   *
   * 全是异步的(写字也是):服务端摆好占位、起好任务就回,产出由回执填回画布,这里只负责发起 + 轮询到结果为止。
   * 占位带着任务号,格子上转圈、能停。
   */
  const run = React.useCallback(
    async (request: BoardRunRequest) => {
      //: 画布的变化攒到停手才汇上来(见 useBoardHistory):先把现在这一份拿出来存上,再等在路上的保存都落地。
      const latest = api?.flush();
      if (latest && !(await save(latest).then(() => true, () => false))) return;
      if (!(await flushSaves())) return;
      //: 版本号**轮到它时再读** —— 排在它前面的写请求可能刚把画布推进到下一版。
      const send = () =>
        serially(() => runOnBoard(board.id, { ...request, workspace_id: workspaceId, base_revision: revision.current }));
      //: 撞了版本号(服务端刚写了一格 —— 别的格子的占位、回执 —— 或智能体改了板):合上最新那一版、把合好的
      //: 存上,再发一次。这一格要跑什么是人刚点的,和服务端那一版推进到哪儿无关;只重来一次,再撞就照常报错。
      const attempt = async (retried: boolean): Promise<Board> => {
        try {
          return await send();
        } catch (error) {
          if (retried || !(await recoverConflict(error))) throw error;
          await save(localCanvas.current ?? confirmedCanvas.current);
          return attempt(true);
        }
      };
      let placed: Board;
      try {
        placed = await attempt(false);
      } catch (error) {
        toast.error(t(isNodeProducer(request.producer) ? "boardToolFailed" : RUN_FAILED[request.producer]), {
          description: (error as Error).message,
        });
        return;
      }
      //: **走画布的把手落到本地**(回写这里的 canvas 状态没用 —— 画布的节点只在挂载时从 canvas 建一次)。
      //: 已经在画布上的那一格(在空槽里生成、截挂了就地重截)换上服务端的表单、运行态和产出 —— 马上标成「在跑」,
      //: 不然用户看到的是「点了没反应」,然后再点一次;新的一格(从一段片子上截)加进去。和别的服务端新版一样
      //: 按格子合进本地:请求在路上时人又拖了、又敲了的照留。
      adoptServer(placed);
      const made = placed.canvas.items.find((one) => one.id === request.item_id);
      setRunning((current) => (current.includes(request.item_id) ? current : [...current, request.item_id]));
      //: `@` 到的资产(或连进来的资产格)挂不全参考图时说一声(ADR 0027):挂了几张、没挂上的为什么。
      //: 只在这一次真的点名了资产时去问(正文里 @ 的,或者连进来的资产格)。
      const named =
        request.producer === "generate" &&
        ((request.form.entity_ids?.length ?? 0) > 0 ||
          (localCanvas.current?.edges ?? []).some(
            (edge) =>
              edge.target === request.item_id &&
              localCanvas.current?.items.some((one) => one.id === edge.source && one.kind === "entity"),
          ));
      if (named && made?.run?.job_id) void announceEntityReceipt(made.run.job_id, t);
    },
    [api, board.id, workspaceId, t, adoptServer, recoverConflict, save, serially, flushSaves],
  );

  /**
   * 停下一格正在跑的那一轮 —— **每一种在跑的格子都有停止**(生成、念、写、截、工具,见 boardNodes 的运行态外壳)。
   * 走任务中心的那一个取消(cancel_job):插件进程登记在这个任务名下,取消就被杀掉;节点派生的子任务
   * (转写、分离……)一并取消。那一格的「已取消」由回执落回来,这里照常轮询收尾。
   */
  const stop = React.useCallback(
    async (itemId: string) => {
      const item = localCanvas.current?.items.find((one) => one.id === itemId);
      const jobId = item?.run?.job_id;
      if (!jobId) return;
      try {
        await cancelJob(jobId);
      } catch (error) {
        toast.error(t("boardToolStopFailed"), { description: (error as Error).message });
      }
    },
    [t],
  );

  /** 取某一帧,存成一份新素材、落到一个新节点上。**是图片节点** —— 取出来的是一张图。 */
  const grabFrame = React.useCallback(
    async (input: { assetId: string; at: number; x: number; y: number }) => {
      try {
        const made = await grabAssetFrame(input.assetId, input.at);
        //: 直接就有 asset_id —— 取帧是同步的一次 ffmpeg,没有「生成中」这个状态。
        api?.add("image", { asset_id: made.id, x: input.x, y: input.y });
      } catch (error) {
        toast.error(t("boardGrabFrameFailed"), { description: (error as Error).message });
      }
    },
    [api, t],
  );

  //: 还在跑的那几格。**轮询而不是等** —— 生成要几十秒,而用户这期间还在画布上干别的。
  const [running, setRunning] = React.useState<string[]>([]);
  // 重进画板、切走再回来、应用重启都不能丢掉轮询。运行状态住在节点里，因此直接从节点
  // 恢复待观察列表，而不是依赖这个组件一次挂载期内的临时 state。
  React.useEffect(() => {
    const ids = (canvas?.items ?? board.canvas.items).filter(itemIsRunning).map((item) => item.id);
    //: 名单真的多了一格才换一份 —— 每次编辑都换一份新数组的话,下面的定时器跟着重来一次。
    setRunning((current) => {
      const joined = ids.filter((id) => !current.includes(id));
      return joined.length ? [...current, ...joined] : current;
    });
  }, [board.id, board.canvas.items, canvas]);
  React.useEffect(() => {
    if (running.length === 0) return;
    const timer = setInterval(async () => {
      const fresh = await getBoard(board.id, workspaceId).catch(() => null);
      if (!fresh) return;
      //: 服务端那一版(连同一次多张的其余几张、派生出来的几格)和它的版本号一起采用,本地没存的改动合在上面
      //: (见 adoptServer)—— 不再因为本地有改动就不采用,那样下一次保存必撞 409。排进写队列:和在路上的保存
      //: 按先后来,保存先回来把版本推过去的话,这份旧的就不采用了。
      await serially(async () => {
        adoptServer(fresh);
      });
      const settled: string[] = [];
      for (const id of running) {
        const item = fresh.canvas.items.find((one) => one.id === id);
        //: 整项没了(比如别处把它删了):没什么可等的了。
        if (!item) {
          settled.push(id);
          continue;
        }
        //: 服务端那一格不在跑了(产出到了、跑挂了、被取消):整组写回本地。**跑挂了也要落到画布
        //: 上** —— 画布的节点只在挂载时从 canvas 建一次,不告诉它的话那一格一直保留 running:
        //: 框里持续转圈,底下那个提交按钮也一直按不动。
        const patch = boardSettlementPatch(item);
        if (!patch) continue;
        api?.patch(id, patch);
        settled.push(id);
      }
      if (settled.length) setRunning((current) => current.filter((id) => !settled.includes(id)));
    }, 2500);
    return () => clearInterval(timer);
  }, [running, board.id, workspaceId, api, adoptServer, serially]);

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
    return listenKeys(window, onKey);
    // 空依赖:这个监听不读任何会变的东西(它用 querySelector 现找那个按钮)。
    // 漏掉依赖数组的话,每次渲染都要拆一次装一次 —— 而画布拖动时那是每帧一次。
  }, []);


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
    serially(() => updateBoard(board.id, { workspace_id: workspaceId, base_revision: revision.current, name: next }))
      .then((fresh) => {
        acceptBoard(fresh);
        setRenaming(false);
      })
      .catch(async (error: Error) => {
        if (!(await recoverConflict(error))) toast.error(error.message);
      })
      .finally(() => setSavingName(false));
  };

  // 画布铺满,操作那组胶囊浮在右上。「这是哪一张、回哪儿去」写在顶栏的路径里(创意画板 / 这张板,
  // 见 components/layout/pageTrail),点名字改名 —— 画布左上角不再摆一颗「返回 · 名字」。
  return (
    <div className="relative grid h-full min-h-0">
      <div className="pointer-events-none absolute inset-x-2 top-2 z-20 flex items-start justify-end gap-2 [&>*]:pointer-events-auto">

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
                //: 「素材」一行挑三种:挑中哪一种就放哪一种格子。
                if (kind === "pick-media") {
                  //: 和拖进来的文件写同样的字段(素材 + 它的名字,boardPlacement.assetFields)。
                  setPicking({ kind: "media", withDocuments: true, place: (asset) => api?.add(asset.kind, assetFields(asset)) });
                } else if (kind === "sequence-new") {
                  //: 时间线格背后是一条正常的时间线(ADR 0030):先建好(放进这张画板的同名项目),再放格子。
                  void createBoardSequence(board.id, workspaceId)
                    .then((made) => api?.add("sequence", { sequence_id: made.sequence_id, text: made.name }))
                    .catch((error: unknown) => toast.error(errorText(error)));
                } else if (kind === "scene-new") {
                  //: 一格空的 3D 场景:连一段剧本进来,按剧本搭白模(场景格的这种填法就是它自己的产出者)。
                  api?.add("scene", { form: { producer: SCENE_FROM_TEXT } });
                } else if (kind === "scene") {
                  setPickingScene(true);
                } else if (kind === "entity") {
                  setPickingEntity(true);
                } else {
                  api?.add(kind as "note" | "image" | "video" | "audio" | "frame" | "document");
                }
              }}
              searchPlaceholder={t("boardsAddItem")}
              options={addOptions}
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
              onJump={(marker) => api?.jumpToMarker(marker)}
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
        onChange={onCanvasChange}
        onPickAsset={(kind, place, options) => setPicking({ kind, place: (asset) => place(asset.id), onBoard: options?.onBoard })}
        onRun={run}
        onGrabFrame={grabFrame}
        models={models.options}
        producers={producers.data}
        onStop={stop}
        showMinimap={showMinimap}
        edgeShape={edgeShape}
        searchHighlight={searchHit}
        onDropFiles={importFiles}
        uploading={upload.isPending}
        commentMode={commentMode}
        markerMode={markerMode}
        markersVisible={markersVisible}
        onRevealMarkers={revealMarkers}
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

      {workspaceId && (
        <EntityPickerDialog
          workspaceId={workspaceId}
          open={pickingEntity}
          onOpenChange={setPickingEntity}
          onPick={(entity) => api?.add("entity", { entity_id: entity.id })}
        />
      )}

      <AssetPickerDialog
        open={picking !== null}
        kind={picking?.kind ?? "image"}
        onBoard={picking?.onBoard}
        withDocuments={picking?.withDocuments}
        workspaceId={workspaceId}
        onOpenChange={(next) => !next && setPicking(null)}
        onPick={(asset) => {
          picking?.place(asset);
          setPicking(null);
        }}
      />
    </div>
  );
}
