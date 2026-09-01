import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, LayoutGrid, Map as MapIcon, Maximize2, Plus, Redo2, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";

import {
  api as api2,
  createBoard,
  deleteBoard,
  generateOnBoard,
  grabAssetFrame,
  speakOnBoard,
  trimOnBoard,
  writeOnBoard,
  getBoard,
  importAsset,
  listBoards,
  updateBoard,
  type GenerationModel,
  type Board,
  type BoardCanvas as Canvas,
  type BoardItem,
  type Workspace,
} from "@/api/client";
import type { MediaKind } from "@/features/boards/boardNodes";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { CanvasTitle } from "@/components/app/canvasTitle";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { usePersistentSelection, usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { CanvasAgentChat, type CanvasAgentMode } from "@/components/agent/CanvasAgentChat";
import { SIDEBAR_HANDLE_CLASS, useResizableSidebar } from "@/lib/useResizableSidebar";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { useAutosave } from "@/features/boards/useAutosave";
import { AssetPickerDialog } from "@/features/boards/AssetPickerDialog";
import { boardSettlementPatch, itemError, itemIsRunning, itemJobId } from "@/features/boards/boardItemState";
import { runNoteWrite, type NoteWriteInput } from "@/features/boards/noteWriteLifecycle";

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
  const [renaming, setRenaming] = React.useState(false);
  const [confirmingDelete, setConfirmingDelete] = React.useState(false);

  //: 画布上的助手。**和工作流那扇是同一个面板** —— 会话池、消息、确认卡都走同一套 agent
  //: session,两边的差别只有附给智能体的那行上下文。各记各的停靠状态和宽度:在画板上
  //: 摊开助手,不该把工作流那边也改了。
  const [agentOpen, setAgentOpen] = usePersistentTab<"on" | "off">("board-agent", "off", ["on", "off"]);
  const [agentMode, setAgentMode] = usePersistentTab<CanvasAgentMode>("board-agent-mode", "docked", ["docked", "floating"]);
  const agentPanel = useResizableSidebar("board-right", { min: 320, max: 640, fallback: 400 });
  const dockedAgent = agentOpen === "on" && agentMode === "docked";
  //: 全览默认开着 —— 大图时它最有用,而"图大不大"只有用户自己知道。记在本地。
  const [minimapMode, setMinimap] = usePersistentTab<"on" | "off">("board-minimap", "on", ["on", "off"] as const);
  const showMinimap = minimapMode === "on";
  const [canvas, setCanvas] = React.useState<Canvas | null>(null);
  const [picking, setPicking] = React.useState<{ kind: MediaKind; place: (assetId: string) => void } | null>(null);
  //: 画布交出来的把手。顶栏那组按钮要和身份胶囊并排,而它们依赖画布内部状态。
  //: **类型从画布导出**,别在这儿再抄一份 —— 抄的那份少一个动作不会报错,只会让按钮点了没反应。
  const [api, setApi] = React.useState<BoardCanvasApi | null>(null);

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
          item_id: itemId,
          kind: input.kind,
          prompt: input.prompt,
          x: input.x ?? 0,
          y: input.y ?? 0,
          provider: input.provider,
          model: input.model,
          parameters: input.parameters,
          source_assets: input.sourceAssets,
          form: input.form,
        });
      } catch (error) {
        toast.error(t("boardsGenerateFailed"), { description: (error as Error).message });
        return;
      }
      //: **马上把那一格标成「在生成」**。服务端已经摆好占位了,但画布的节点只在挂载时从
      //: canvas 建一次 —— 不主动告诉它的话,节点还是个空槽、面板也不收:用户看到的就是
      //: 「点了没反应」,然后再点一次。
      //: 上一次的报错要一起清掉 —— 重来一次的时候还挂着上次为什么挂,用户会以为这次也挂了。
      const pending = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === itemId);
      const jobId = pending ? itemJobId(pending) : undefined;
      if (jobId) api?.patch(itemId, { form: pending?.form ?? input.form, run: { status: "running", job_id: jobId }, job_id: undefined, error: undefined });
      setRunning((current) => (current.includes(itemId) ? current : [...current, itemId]));
    },
    [board.id, workspaceId, t, api],
  );

  /** 让 AI 往某张便签里写字。同步返回,写完直接把新画布落回本地状态。 */
  const write = React.useCallback(
    async (input: NoteWriteInput) => {
      try {
        await runNoteWrite({
          input,
          patch: (itemId, next) => api?.patch(itemId, next),
          request: () =>
            writeOnBoard(board.id, {
              workspace_id: workspaceId,
              item_id: input.itemId,
              prompt: input.prompt,
              provider_profile_id: input.providerProfileId,
              model: input.model,
              source_assets: input.assets,
              context: input.context,
            }),
        });
        onSaved();
      } catch (error) {
        toast.error(t("boardWriteFailed"), { description: (error as Error).message });
      }
    },
    [board.id, workspaceId, onSaved, api, t],
  );

  /** 把一段文字念成音频。**异步** —— 和出图出片同一套:摆占位、起任务、轮询等回执填回来。 */
  const speak = React.useCallback(
    async (input: { itemId: string; text: string; voiceId: string }) => {
      let placed;
      try {
        placed = await speakOnBoard(board.id, {
          workspace_id: workspaceId,
          item_id: input.itemId,
          text: input.text,
          voice_id: input.voiceId,
        });
      } catch (error) {
        toast.error(t("boardSpeakFailed"), { description: (error as Error).message });
        return;
      }
      //: 和生成那条一样:马上把这一格标成在跑,不然画布上看不出发生了什么。
      const pending = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === input.itemId);
      const jobId = pending ? itemJobId(pending) : undefined;
      if (jobId) api?.patch(input.itemId, { run: { status: "running", job_id: jobId }, job_id: undefined, error: undefined });
      setRunning((current) => (current.includes(input.itemId) ? current : [...current, input.itemId]));
    },
    [board.id, workspaceId, api, t],
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
          item_id: input.itemId,
          asset_id: input.assetId,
          start: input.start,
          end: input.end,
          mute: input.mute,
          x: input.x,
          y: input.y,
        });
      } catch (error) {
        toast.error(t("boardTrimFailed"), { description: (error as Error).message });
        return;
      }
      //: **走画布的把手把新那一格加进去。** 回写这里的 canvas 状态是没用的 —— 画布的节点
      //: 只在挂载时从 canvas 建一次(和写文案那条同一个坑)。
      const made = ((placed.canvas?.items ?? []) as BoardItem[]).find((one) => one.id === input.itemId);
      if (made) api?.add(made.kind, made);
      onSaved();
      setRunning((current) => [...current, input.itemId]);
    },
    [board.id, workspaceId, onSaved, api, t],
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
      const settled: string[] = [];
      for (const id of running) {
        const item = fresh.canvas.items.find((one) => one.id === id);
        //: 整项没了(比如别处把它删了):没什么可等的了。
        if (!item) {
          settled.push(id);
        } else if (item.asset_id) {
          //: 产出到了:填上 asset_id,并把 job_id 摘掉 —— 两个都在的话画布不知道该画转圈还是画图。
          api?.patch(id, boardSettlementPatch(item) ?? {});
          settled.push(id);
        } else if (itemError(item)) {
          //: **跑挂了也要落到画布上。** 此前这里只把 id 从「还在等」的名单里划掉,却没告诉
          //: 画布 —— 而画布的节点只在挂载时从 canvas 建一次,那一格于是永远带着 job_id:
          //: 框里一直转圈,底下那个提交按钮(busy 看的就是 job_id)也一直按不动。
          api?.patch(id, boardSettlementPatch(item) ?? {});
          settled.push(id);
        }
      }
      if (settled.length) setRunning((current) => current.filter((id) => !settled.includes(id)));
    }, 2500);
    return () => clearInterval(timer);
  }, [running, board.id, workspaceId, api]);

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
  });

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

  //: 改名走**全站那一个** RenameDialog(设置、首页、会话列表、工作流都走它)。此前这里是
  //: 就地把标题换成一个输入框 —— 少一处确认、少一条校验(空名靠 onBlur 悄悄回滚),
  //: 而"改个名字"在这个应用里已经有答案了,画板没有理由是第九种。
  const rename = (next: string) => {
    setRenaming(false);
    if (next === board.name) return;
    updateBoard(board.id, { workspace_id: workspaceId, name: next })
      .then(onSaved)
      .catch((error: Error) => toast.error(error.message));
  };

  // 版式跟着工作流详情页:**画布铺满,两组胶囊浮在上面** —— 左边是身份(回哪儿去、这是谁),
  // 右边是操作。悬浮不等于没有边界:两组各有自己的底,否则它们会散在画布上和内容抢注意力。
  return (
    <div className="relative grid h-full min-h-0 p-2">
      <div className="pointer-events-none absolute inset-x-4 top-4 z-20 flex flex-wrap items-start justify-between gap-2 [&>*]:pointer-events-auto">
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


        {/* 右上角**分组胶囊**,刻度和工作流详情页一致:胶囊 rounded-full、图标钮 h-8 w-8、
            bg-panel/95 + backdrop-blur。分三组是按"这是哪一类动作"分的 ——
            往画布上加东西 / 看画布 / 处置这张板。混成一条的话,删除会挨着「加便签」。 */}
        <div className="flex flex-wrap items-start justify-end gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
            {/* 「往画布上加东西」收成一个 + —— 和工作流详情页的「添加节点」同一颗控件
                (SearchableSelect):六个图标排一排要逐个认,弹层里名字写出来就不用猜。
                「贴一份现成的」和「放一个空槽去生成」是两件事,弹层里分成两组。 */}
            <SearchableSelect
              value=""
              onValueChange={(kind) => {
                if (kind === "pick-image") {
                  setPicking({ kind: "image", place: (assetId) => api?.add("image", { asset_id: assetId }) });
                } else {
                  api?.add(kind as "note" | "image" | "video" | "audio" | "frame");
                }
              }}
              searchPlaceholder={t("boardsAddItem")}
              options={[
                { value: "note", label: t("boardsAddNote"), group: t("boardsGroupCreate") },
                { value: "image", label: t("boardsAddImage"), group: t("boardsGroupCreate") },
                { value: "video", label: t("boardsAddVideo"), group: t("boardsGroupCreate") },
                { value: "audio", label: t("boardsAddAudio"), group: t("boardsGroupCreate") },
                { value: "frame", label: t("boardsAddFrame"), group: t("boardsGroupCreate") },
                { value: "pick-image", label: t("boardsPickImage"), group: t("boardsGroupAssets") },
              ]}
              trigger={
                <button
                  type="button"
                  data-board-add-item=""
                  className="grid h-8 w-8 place-items-center rounded-full border-0 bg-transparent text-foreground transition-colors hover:bg-secondary"
                  aria-label={t("boardsAddItem")}
                  title={`${t("boardsAddItem")} ⌘N`}
                >
                  <Plus size={15} />
                </button>
              }
            />
          </div>

          <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
            {/* 全览可关 —— 它占着右下角一块不小的地方,图小的时候纯属挡视线。记在本地。 */}
            <Button
              variant="ghost"
              size="icon"
              className={cn("h-8 w-8", showMinimap && "bg-secondary text-foreground")}
              title={t("wfMinimap")}
              aria-label={t("wfMinimap")}
              aria-pressed={showMinimap}
              onClick={() => setMinimap(showMinimap ? "off" : "on")}
            >
              <MapIcon size={14} />
            </Button>
            <Button variant="ghost" size="icon" className="h-8 w-8" title={t("boardsFitView")} aria-label={t("boardsFitView")} onClick={() => api?.fitView()}>
              <Maximize2 size={14} />
            </Button>
            {/* 撤销/重做。画布上最容易「手一滑」—— 拖错一个节点、误删一项,没有退路的话
                用户只能凭记忆手动摆回去。快捷键是 ⌘Z / ⌘⇧Z,按钮是给不知道有快捷键的人。 */}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title={`${t("undo")}  ⌘Z`}
              aria-label={t("undo")}
              disabled={!api?.canUndo}
              onClick={() => api?.undo()}
            >
              <Undo2 size={14} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title={`${t("redo")}  ⌘⇧Z`}
              aria-label={t("redo")}
              disabled={!api?.canRedo}
              onClick={() => api?.redo()}
            >
              <Redo2 size={14} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={cn("h-8 w-8", agentOpen === "on" && "bg-secondary text-foreground")}
              title={t("wfAgentTitle")}
              aria-label={t("wfAgentTitle")}
              aria-pressed={agentOpen === "on"}
              onClick={() => setAgentOpen(agentOpen === "on" ? "off" : "on")}
            >
              <Bot size={14} />
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-1 rounded-full border border-border bg-panel/95 p-1 shadow-[var(--shadow-panel)] backdrop-blur">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 hover:text-destructive"
              title={t("delete")}
              aria-label={t("delete")}
              onClick={() => setConfirmingDelete(true)}
            >
              <Trash2 size={14} />
            </Button>
          </div>
        </div>
      </div>

      {agentOpen === "on" && (
        // 停靠时贴右侧,从工具条底下起、到画布底边止(和工作流详情页同一套刻度);
        // 切到浮动模式后它自己脱离文档流,这一层就只是个容器。
        <div
          className={cn(
            "z-10 grid min-h-0 min-w-0",
            //: 起点算出来的,不是抄工作流那个 54:这一页的工具条挂在 top-4(容器内 16px)、
            //: 高 42px,底边落在 58px —— 再留 8px 才是这里的 66。抄数字的话删除键会叠在面板上。
            dockedAgent && "absolute bottom-2 right-2 top-[66px]",
          )}
          style={dockedAgent ? { width: agentPanel.width } : undefined}
        >
          <CanvasAgentChat
            contextLine={t("boardAgentContext").replace("{id}", board.id).replace("{name}", board.name)}
            emptyHint={t("boardAgentEmpty")}
            placeholder={t("boardAgentPlaceholder")}
            rectKey="openstudio.board.agent.rect.v1"
            workspaceId={workspaceId}
            mode={agentMode}
            onModeChange={setAgentMode}
            onClose={() => setAgentOpen("off")}
          />
        </div>
      )}
      {dockedAgent && (
        <div
          className={SIDEBAR_HANDLE_CLASS}
          style={{ right: agentPanel.width + 4 }}
          onPointerDown={agentPanel.startDrag}
        />
      )}

      <BoardCanvas
        boardId={board.id}
        workspaceId={workspaceId}
        canvas={board.canvas ?? { items: [], edges: [] }}
        onChange={setCanvas}
        onPickAsset={(kind, place) => setPicking({ kind, place })}
        onGenerate={generate}
        onWrite={write}
        onSpeak={speak}
        onTrim={trim}
        onGrabFrame={grabFrame}
        models={models.data ?? []}
        showMinimap={showMinimap}
        onDropFiles={(files) => upload.mutateAsync(files)}
        uploading={upload.isPending}
        onReady={setApi}
      />

      <RenameDialog
        open={renaming}
        title={t("rename")}
        initialValue={board.name}
        onCancel={() => setRenaming(false)}
        onSubmit={rename}
      />

      <ConfirmDialog
        open={confirmingDelete}
        title={t("boardsDeleteTitle")}
        body={board.name}
        onCancel={() => setConfirmingDelete(false)}
        onConfirm={() => {
          setConfirmingDelete(false);
          void deleteBoard(board.id, workspaceId).then(() => {
            onSaved();
            onBack();
          });
        }}
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
