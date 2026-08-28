import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, LayoutGrid, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  createBoard,
  deleteBoard,
  listBoards,
  updateBoard,
  type Board,
  type BoardCanvas as Canvas,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { BoardCanvas } from "@/features/boards/BoardCanvas";
import { useAutosave } from "@/features/boards/useAutosave";
import { AssetPickerDialog } from "@/features/boards/AssetPickerDialog";

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
  const [openId, setOpenId] = usePersistentSelection(
    `boards:${workspace.id}`,
    list.map((board) => board.id),
  );
  const open = list.find((board) => board.id === openId) ?? null;

  const create = useMutation({
    mutationFn: () => createBoard({ workspace_id: workspace.id }),
    onSuccess: (board) => {
      void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] });
      setOpenId(board.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: (boardId: string) => deleteBoard(boardId, workspace.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] }),
    onError: (error: Error) => toast.error(error.message),
  });

  if (open) {
    return (
      <BoardDetail
        board={open}
        workspaceId={workspace.id}
        onBack={() => setOpenId(null)}
        onSaved={() => void queryClient.invalidateQueries({ queryKey: ["boards", workspace.id] })}
      />
    );
  }

  // 容器、内边距、卡片栅格都跟着工作流列表页走 —— 同一层级的两个页面长得不一样,
  // 用户会以为自己切到了别的应用里。
  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
      <div className="flex items-center justify-between pb-2">
        <h2 className="m-0 inline-flex items-center gap-1.5 text-ui-md font-semibold text-foreground">
          <LayoutGrid size={13} /> {t("navBoards")}
        </h2>
        <Button size="sm" loading={create.isPending} onClick={() => create.mutate()}>
          <Plus size={13} /> {t("boardsNew")}
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {boards.isLoading ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-[74px] rounded-lg" />
            ))}
          </div>
        ) : list.length === 0 ? (
          // **撑满再居中。** EmptyState 自带 m-auto,但它只在父级真的给了高度时才起作用 ——
          // 少了这层 h-full,空态会贴在顶上,看着像没加载完。
          <div className="grid h-full place-items-center">
            <EmptyState icon={<LayoutGrid size={22} />} title={t("boardsEmptyTitle")} body={t("boardsEmptyHint")} />
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
            {list.map((board) => (
              <BoardCard
                key={board.id}
                board={board}
                onOpen={() => setOpenId(board.id)}
                onDelete={() => remove.mutate(board.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function BoardCard({ board, onOpen, onDelete }: { board: Board; onOpen: () => void; onDelete: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [confirming, setConfirming] = React.useState(false);
  const count = board.canvas?.items?.length ?? 0;

  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        className="group grid cursor-pointer gap-1 rounded-lg border border-border bg-panel p-3 text-left transition-colors hover:border-border-strong"
      >
        <div className="flex items-start justify-between gap-2">
          <span className="truncate text-ui-sm font-medium text-foreground">{board.name}</span>
          <span
            role="button"
            tabIndex={0}
            aria-label={t("delete")}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
            onClick={(event) => {
              event.stopPropagation();
              setConfirming(true);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.stopPropagation();
              setConfirming(true);
            }}
          >
            <Trash2 size={13} />
          </span>
        </div>
        <span className="text-ui-2xs text-muted-foreground">
          {t("boardsItemCount").replace("{n}", String(count))} · {relativeTime(board.updated_at, locale)}
        </span>
      </button>
      <ConfirmDialog
        open={confirming}
        title={t("boardsDeleteTitle")}
        body={board.name}
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          onDelete();
        }}
      />
    </>
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
  const [name, setName] = React.useState(board.name);
  const [canvas, setCanvas] = React.useState<Canvas | null>(null);
  const [picking, setPicking] = React.useState<{ kind: "image" | "video"; place: (assetId: string) => void } | null>(null);

  const save = React.useCallback(
    (next: Canvas) => {
      updateBoard(board.id, { workspace_id: workspaceId, canvas: next })
        .then(onSaved)
        // 存不上必须说 —— 画板是攒想法的地方,默默丢掉是最糟的失败方式。
        .catch((error: Error) => toast.error(t("boardsSaveFailed"), { description: error.message }));
    },
    [board.id, workspaceId, onSaved, t],
  );
  const { pending } = useAutosave(canvas, save);

  const rename = () => {
    const cleaned = name.trim();
    if (!cleaned || cleaned === board.name) return setName(board.name);
    updateBoard(board.id, { workspace_id: workspaceId, name: cleaned })
      .then(onSaved)
      .catch((error: Error) => toast.error(error.message));
  };

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onBack} aria-label={t("back")}>
          <ChevronLeft size={15} />
        </Button>
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onBlur={rename}
          onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
          className="h-7 w-56 border-0 bg-transparent px-1 text-ui-sm font-semibold shadow-none focus-visible:bg-field"
          aria-label={t("boardsName")}
        />
        {/* 自动保存本来就该是无声的,但**攒着还没发**的那一刻要让人看见 —— 否则切走时
            用户不知道自己是不是走早了。 */}
        <span className="ml-auto text-ui-2xs text-muted-foreground">
          {pending ? t("boardsSaving") : t("boardsSaved")}
        </span>
      </div>

      <BoardCanvas
        boardId={board.id}
        canvas={board.canvas ?? { items: [], edges: [] }}
        onChange={setCanvas}
        onPickAsset={(kind, place) => setPicking({ kind, place })}
      />

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
