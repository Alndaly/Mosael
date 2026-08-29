import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Film, FolderOpen, Image as ImageIcon, LayoutGrid, Plus, Square, StickyNote, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  api as api2,
  createBoard,
  deleteBoard,
  generateOnBoard,
  getBoard,
  listBoards,
  updateBoard,
  type GenerationModel,
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
  const [renaming, setRenaming] = React.useState(false);
  const [canvas, setCanvas] = React.useState<Canvas | null>(null);
  const [picking, setPicking] = React.useState<{ kind: "image" | "video"; place: (assetId: string) => void } | null>(null);
  //: 画布交出来的「加一项」。顶栏那组按钮要和身份胶囊并排,而 add 依赖画布内部状态。
  const [api, setApi] = React.useState<{
    add: (kind: "note" | "image" | "video" | "frame", extra?: Record<string, unknown>) => void;
    fill: (itemId: string, assetId: string) => void;
  } | null>(null);

  // 提示词面板要让人选模型 —— 两种能力各取一次再合并,和 AI 工作台看到的是同一份。
  const models = useQuery({
    queryKey: ["generation-options", "board"],
    queryFn: async () => {
      const [image, video] = await Promise.all([
        api2<GenerationModel[]>("/api/generation/options?kind=image"),
        api2<GenerationModel[]>("/api/generation/options?kind=video"),
      ]);
      return [...image, ...video];
    },
    staleTime: 60_000,
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
      model?: string;
      sourceAssetId?: string;
    }) => {
      const itemId = input.itemId ?? `${input.kind}-${Math.random().toString(36).slice(2, 9)}`;
      try {
        await generateOnBoard(board.id, {
          workspace_id: workspaceId,
          item_id: itemId,
          kind: input.kind,
          prompt: input.prompt,
          x: input.x ?? 0,
          y: input.y ?? 0,
          provider: input.provider,
          model: input.model,
          source_assets: input.sourceAssetId
            ? [{ asset_id: input.sourceAssetId, role: "first_frame" }]
            : undefined,
        });
      } catch (error) {
        toast.error(t("boardsGenerateFailed"), { description: (error as Error).message });
        return;
      }
      setRunning((current) => [...current, itemId]);
    },
    [board.id, workspaceId, t],
  );

  //: 还在跑的那几格。**轮询而不是等** —— 生成要几十秒,而用户这期间还在画布上干别的。
  const [running, setRunning] = React.useState<string[]>([]);
  React.useEffect(() => {
    if (running.length === 0) return;
    const timer = setInterval(async () => {
      const fresh = await getBoard(board.id, workspaceId).catch(() => null);
      if (!fresh) return;
      const settled: string[] = [];
      for (const id of running) {
        const item = fresh.canvas.items.find((one) => one.id === id);
        // 找不到 = 任务失败,后端把占位摘了 —— 这一格也就不用再等。
        if (!item) settled.push(id);
        else if (item.asset_id) {
          api?.fill(id, item.asset_id);
          settled.push(id);
        }
      }
      if (settled.length) setRunning((current) => current.filter((id) => !settled.includes(id)));
    }, 2500);
    return () => clearInterval(timer);
  }, [running, board.id, workspaceId, api]);

  const save = React.useCallback(
    (next: Canvas) => {
      updateBoard(board.id, { workspace_id: workspaceId, canvas: next })
        .then(onSaved)
        // 存不上必须说 —— 画板是攒想法的地方,默默丢掉是最糟的失败方式。
        .catch((error: Error) => toast.error(t("boardsSaveFailed"), { description: error.message }));
    },
    [board.id, workspaceId, onSaved, t],
  );
  // **不显示"已保存"。** 自动保存做对了就该是无声的:一个常驻的「已保存」既不能让人放心
  // (它任何时候都这么写),又占着顶栏一格。失败仍然会 toast —— 那才是需要打断的时刻。
  useAutosave(canvas, save);

  const rename = () => {
    const cleaned = name.trim();
    if (!cleaned || cleaned === board.name) return setName(board.name);
    updateBoard(board.id, { workspace_id: workspaceId, name: cleaned })
      .then(onSaved)
      .catch((error: Error) => toast.error(error.message));
  };

  // 版式跟着工作流详情页:**画布铺满,两组胶囊浮在上面** —— 左边是身份(回哪儿去、这是谁),
  // 右边是操作。悬浮不等于没有边界:两组各有自己的底,否则它们会散在画布上和内容抢注意力。
  return (
    <div className="relative grid h-full min-h-0 p-2">
      <div className="pointer-events-none absolute inset-x-4 top-4 z-20 flex flex-wrap items-start justify-between gap-2 [&>*]:pointer-events-auto">
        <div className="flex items-center gap-1 rounded-full border border-border bg-panel/95 p-1 pr-2.5 shadow-[var(--shadow-panel)] backdrop-blur">
          {/* 返回键给它一个底:透明底的图标钮在胶囊里没有自己的轮廓,和右边的竖线对不齐。 */}
          <Button
            variant="secondary"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={onBack}
            title={t("navBoards")}
            aria-label={t("navBoards")}
          >
            <ChevronLeft size={16} />
          </Button>
          {/* 一个是「离开这里」,一个是「这里是什么」—— 两件事,挨着放需要一道界。 */}
          <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />
          {/* **贴着内容,不给固定宽度。** 定宽的输入框在只有三个字的名字下面是一个大空格子,
              看着像没加载完 —— 工作流那边是一个点开才变输入框的按钮,这里同理。 */}
          {renaming ? (
            <Input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => {
                rename();
                setRenaming(false);
              }}
              onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
              className="h-7 w-40 border-0 bg-field px-1.5 text-ui-md font-semibold shadow-none"
              aria-label={t("boardsName")}
            />
          ) : (
            <button
              type="button"
              className="inline-flex cursor-pointer items-center rounded-full border-0 bg-transparent px-1.5 py-[3px] text-ui-md font-semibold text-foreground hover:bg-secondary"
              onClick={() => setRenaming(true)}
              title={t("rename")}
            >
              {board.name}
            </button>
          )}
        </div>

      </div>

      {/* 加什么:**竖排,贴左侧** —— 画布要尽量大,而这几个是"一直都在"的入口(tapnow 同款)。
          横在顶上的话它和身份胶囊挤成一行,画布还要为它让出一整行。 */}
      <div className="pointer-events-auto absolute left-4 top-1/2 z-20 flex -translate-y-1/2 flex-col items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
        <Button variant="ghost" size="icon" className="h-8 w-8" title={t("boardsAddNote")} aria-label={t("boardsAddNote")} onClick={() => api?.add("note")}>
          <StickyNote size={15} />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" title={t("boardsAddImage")} aria-label={t("boardsAddImage")} onClick={() => api?.add("image")}>
          <ImageIcon size={15} />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" title={t("boardsAddVideo")} aria-label={t("boardsAddVideo")} onClick={() => api?.add("video")}>
          <Film size={15} />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" title={t("boardsAddFrame")} aria-label={t("boardsAddFrame")} onClick={() => api?.add("frame")}>
          <Square size={15} />
        </Button>
        <span aria-hidden className="my-0.5 h-px w-4 bg-border" />
        {/* 从素材库贴一份现成的 —— 和"放一个空槽去生成"是两件事,所以分在竖线下面。 */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          title={t("boardsPickImage")}
          aria-label={t("boardsPickImage")}
          onClick={() => setPicking({ kind: "image", place: (assetId) => api?.add("image", { asset_id: assetId }) })}
        >
          <FolderOpen size={15} />
        </Button>
      </div>

      <BoardCanvas
        boardId={board.id}
        canvas={board.canvas ?? { items: [], edges: [] }}
        onChange={setCanvas}
        onPickAsset={(kind, place) => setPicking({ kind, place })}
        onGenerate={generate}
        models={models.data ?? []}
        onReady={setApi}
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
