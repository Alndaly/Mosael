import React from "react";
import { Streamdown } from "streamdown";
import { noteHref, type NoteReference } from "@/api/domains/notes";
import { SaveToNote } from "@/features/notes/SaveToNote";
import { Handle, NodeResizer, Position, useStore, type NodeProps } from "@xyflow/react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpen, ExternalLink, RefreshCw, Replace, Box, Ban, Clock3, Film as FilmIcon, Group, Image as ImageIcon, Music, Plus, Square as SquareIcon, StickyNote, Wrench, type LucideIcon } from "lucide-react";

import { getJob, isNodeProducer, type BoardItem, type BuiltinProducer } from "@/api/client";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { BoardAudio, BoardVideo } from "@/features/boards/BoardPlayer";
import { DraftTextarea } from "@/components/ui/draft-text";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { cn } from "@/lib/utils";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { itemError, itemIsRunning, itemJobId, itemRunStatus, type BoardItemRunStatus } from "@/features/boards/boardItemState";
import { BoardNodeLabel } from "@/features/boards/BoardNodeLabel";

/**
 * 画板上的格子:便签、图片 / 视频 / 音频、文档、3D 场景、分组框,和跑一个工具的工具格。
 *
 * **和工作流节点分开写,不复用。** 两边看着都是"画布上的一个方块",但要的东西正相反:
 * 工作流节点表达的是**一个会执行的步骤**(有输入输出接点、有运行状态、有必填校验),
 * 画板上的东西表达的是**一个想法**(要能随手改大小、随手改颜色、双击就写字)。
 * 硬凑成一个组件的话,每加一个画板专属的交互都要先绕过工作流那套。
 *
 * **画板只有一种视觉语言:格子就是它的内容。** 一张图就是那张图,一段视频是一帧画面加播放键;
 * 空着的格子是一块安静的占位,正中一枚淡淡的图标,名字在格子上方。工具格也照这个画 —— 它长得像
 * 它要产出的那种内容的空格子(见 ActionNode),不是一张缩小的工作流节点或表单。
 */

/** 便签的色板。给固定几种而不是任意色值 —— 一组固定的色才让「黄色是待办、蓝色是参考」成立。 */
export const NOTE_COLORS = ["yellow", "blue", "green", "pink", "purple", "gray"] as const;
export type NoteColor = (typeof NOTE_COLORS)[number];

/** 每种颜色的底 / 边 / 字。用 color-mix 从主题色调出来,深浅主题各自成立。 */
const COLOR_CLASS: Record<NoteColor, string> = {
  yellow: "bg-[color-mix(in_srgb,#f5c518_18%,var(--panel))] border-[color-mix(in_srgb,#f5c518_22%,var(--border))]",
  blue: "bg-[color-mix(in_srgb,#3b82f6_16%,var(--panel))] border-[color-mix(in_srgb,#3b82f6_22%,var(--border))]",
  green: "bg-[color-mix(in_srgb,#22c55e_16%,var(--panel))] border-[color-mix(in_srgb,#22c55e_22%,var(--border))]",
  pink: "bg-[color-mix(in_srgb,#ec4899_15%,var(--panel))] border-[color-mix(in_srgb,#ec4899_22%,var(--border))]",
  purple: "bg-[color-mix(in_srgb,#8b5cf6_16%,var(--panel))] border-[color-mix(in_srgb,#8b5cf6_22%,var(--border))]",
  gray: "bg-[color-mix(in_srgb,var(--foreground)_7%,var(--panel))] border-border",
};

export function noteColorClass(color: string | undefined): string {
  return COLOR_CLASS[(color as NoteColor) ?? "yellow"] ?? COLOR_CLASS.yellow;
}

/** 节点数据 = 画板项本身 + 一个回写文字的回调。React Flow 要求 data 是普通对象。 */
export type BoardNodeData = {
  item: BoardItem;
  workspaceId?: string;
  boardId?: string;
  document?: { reference?: NoteReference; pending: boolean; error?: string };
  onPickDocument?: (id: string) => void;
  onRefreshDocument?: (id: string) => void;
  refreshingDocument?: boolean;
  onText: (id: string, text: string) => void;
  /** 这一格正在改名(双击名字、或操作条上的「重命名」)。状态归画布:两个入口进的是同一个。 */
  renaming?: boolean;
  onRenaming?: (id: string | null) => void;
  /** 改好的名字;空串 = 不要名字了,退回显示种类名。 */
  onRename?: (id: string, title: string) => void;
  /** 媒体加载出来之后报一次自然宽高比 —— 节点据此把高度校正过来,画面才铺得满。 */
  onAspect: (id: string, ratio: number) => void;
  /** 评论模式只接受标注，不暴露会修改画布结构的连线入口。 */
  commentMode?: boolean;
  /** 工具格跑的是哪个工具(从产出者清单里查到的)。null = 这个人此刻用不了它(插件卸了、没有连接);
   *  undefined = 清单还没到。 */
  tool?: BoardToolFace | null;
  /** 停下这一格正在跑的任务。**所有在跑的格子都有**(生成、念、写、截、工具)—— 停止属于运行态的外壳。 */
  onStop?: (id: string) => void;
};

/** 工具格长成哪一种内容的空格子。 */
export type ToolCellKind = "note" | "image" | "video" | "audio";

/**
 * 工具格上要显示的那几样(boardTools.boardToolFace 从工具声明和这一格的表单里读出来):名字、出处
 * (插件名;内置节点为空 —— 「内置」对创作者不是一个有意义的区分)、图标、一句说明(悬停看),
 * 它要产出的是哪种内容(格子就画成那种内容的空格子),以及还差的那一样。
 */
export interface BoardToolFace {
  label: string;
  description: string;
  plugin: string;
  icon: LucideIcon;
  /** 主产出落成哪种格子(ADR 0025 `output_kinds` 的第一个;说不清是哪种素材的按图片格画)。 */
  kind: ToolCellKind;
  /** 还差的那一样:第一个没接上、也没手填的**必填**输入能接哪几种格子。null = 不差。 */
  missing: BoardItem["kind"][] | null;
}

/**
 * 左右两个接点。**画成圆形的 `+`**,选中或悬停时显形。
 *
 * 小圆点只说得出"这里能连线";而用户在画板上真正想做的是**从这一边接着往下长**(tapnow 同款)。
 * 一个 `+` 把这件事说清楚了,而它同时仍是 React Flow 的 Handle —— 拖它就是连线。
 *
 * 默认透明是因为想法之间的关系是次要信息:一上来每个节点四周都挂着圆圈,画布看着像电路图。
 */
function Ports({ visible, disabled = false }: { visible?: boolean; disabled?: boolean }) {
  //: **handle 元素自己要小、要贴着边**,因为连线的锚点是从它的矩形算出来的 —— 把它做大
  //: 或者整个挪出去,线头就跟着跑,节点和线之间裂开一段空白(试过一版横跨边线的大盒子,
  //: 不成立:线头跟着可见的圆圈走了)。
  //:
  //: 所以反过来做:handle 保持一个贴边的小方块(锚点稳稳落在边上),可见的圆圈是它的**子
  //: 元素**,绝对定位溢出到节点外面。圆圈在 handle 里,从它上面往外拖照样能拉线。
  //:
  //: 圆圈**反着视口缩放**,于是它在屏幕上永远这么大 —— 跟着画布缩的话,拉远时它小成一个
  //: 点(点不中),拉近时又胀成一个盘子。同一份 transform 里连位移一起抵消,离节点的那段
  //: 距离也就不会跟着变(transform 从右往左作用,先位移再缩放)。
  const zoom = useStore((state) => state.transform[2]) || 1;
  // Keep handles mounted so undo can remeasure edges in annotation modes.
  //: **锚点是 handle 在那一侧的外边缘,不是中心** —— 源码里 Position.Right 返回 x+width、
  //: Position.Left 返回 x。而默认样式把 handle 居中骑在边线上(translate ±50%),于是线头
  //: 天生就落在边外 width/2 处;handle 越大离得越远(横跨边线的大盒子那版差了 28px)。
  //: 把横向的位移抵掉,让方块整个缩进边内:左侧的左边缘、右侧的右边缘,就都正好压在边上。
  const flush = { transform: "translateY(-50%)" };
  const anchor = "!h-2 !w-2 !rounded-none !border-0 !bg-transparent !p-0 transition-opacity";
  const dot =
    "grid h-6 w-6 place-items-center rounded-full border border-border-strong bg-panel text-muted-foreground transition-colors hover:border-primary hover:text-primary";
  const shown = disabled ? "!opacity-0 !pointer-events-none" : visible ? "opacity-100" : "opacity-0 group-hover:opacity-100";
  const scaled = (offset: number, origin: string) => ({
    transform: `scale(${1 / zoom}) translateX(${offset}px)`,
    transformOrigin: origin,
  });
  return (
    <>
      <Handle isConnectable={!disabled} type="target" position={Position.Left} style={flush} className={cn(anchor, shown)}>
        <span className="absolute right-full top-1/2 -translate-y-1/2">
          <span className={dot} style={scaled(-10, "right center")}>
            <Plus size={13} />
          </span>
        </span>
      </Handle>
      <Handle isConnectable={!disabled} type="source" position={Position.Right} style={flush} className={cn(anchor, shown)}>
        <span className="absolute left-full top-1/2 -translate-y-1/2">
          <span className={dot} style={scaled(10, "left center")}>
            <Plus size={13} />
          </span>
        </span>
      </Handle>
    </>
  );
}

/**
 * 每种节点叫什么、长什么图标、是干嘛的。**只此一处。**
 *
 * 节点左上角的标签、从连线末端长出新节点的那个菜单、工具条 —— 都读它。此前图标和名字散在
 * 各个节点组件里各写一份,于是便签被贴成了「视频」、视频自己反倒没有标签,而两处都不报错。
 */
//: 名字和说明**存的是 i18n 的 key,不是中文**。写死的话切到英文界面这一整排还是中文,
//: 而它们出现在工具条、节点标签、添加菜单三处 —— 漏一处不会报错,只会是半中半英。
//:
//: **别直接读这里的 label / hint 往界面上放** —— 走下面的 kindText():直接读的话拿到的是
//: 「boardKindImage」这串 key 本身,而它长得像个正常字符串,一路挂到菜单上都不会有人拦。
//: 连线菜单就这么漏过一次:四个选项连标题带说明,整整八行显示的全是 key。
const KIND_META: Record<BoardItem["kind"], { icon: LucideIcon; label: MessageKey; hint: MessageKey }> = {
  document: { icon: BookOpen, label: "boardKindDocument", hint: "boardDocumentHint" },
  scene: { icon: Box, label: "boardKindScene", hint: "boardSceneHint" },
  note: { icon: StickyNote, label: "boardKindNote", hint: "boardKindNoteHint" },
  image: { icon: ImageIcon, label: "boardKindImage", hint: "boardKindImageHint" },
  video: { icon: FilmIcon, label: "boardKindVideo", hint: "boardKindVideoHint" },
  audio: { icon: Music, label: "boardKindAudio", hint: "boardKindAudioHint" },
  frame: { icon: SquareIcon, label: "boardKindFrame", hint: "boardKindFrameHint" },
  action: { icon: Wrench, label: "boardKindAction", hint: "boardKindActionHint" },
};

/** 这一类的图标。图标不需要翻译,所以它可以直接拿。 */
export function kindIcon(kind: BoardItem["kind"]): LucideIcon {
  return KIND_META[kind].icon;
}

/**
 * 这一类**给人看的**名字和说明。
 *
 * 传 `t` 而不是自己 `useI18n()`:调用点之一在 `.map()` 里,而 hook 不能在循环里调。
 */
export function kindText(t: (key: MessageKey) => string, kind: BoardItem["kind"]): { label: string; hint: string } {
  const meta = KIND_META[kind];
  return { label: t(meta.label), hint: t(meta.hint) };
}

/**
 * 这一格**叫什么**:起了名就是名字,没起就是种类名(「图片」)。
 *
 * 节点上方那一行、查找节点、画板列表的缩略图都照这一条认 —— 没起名显示种类名是「默认」的定义,
 * 不是兜底。
 */
export function itemName(t: (key: MessageKey) => string, item: Pick<BoardItem, "kind" | "title">): string {
  return item.title?.trim() || kindText(t, item.kind).label;
}

/** 当作**上游**称呼一格(工具格上「接的是哪一格」、面板上的绑定芯片):起了名用名字;便签没起名就用
 *  开头几个字(几张便签都叫「便签」分不开);文档用它的标题。 */
export function sourceName(t: (key: MessageKey) => string, item: BoardItem): string {
  const title = item.title?.trim();
  if (title) return title;
  if (item.kind === "note" && item.text?.trim()) {
    const text = item.text.trim().replace(/\s+/g, " ");
    return text.length > 18 ? `${text.slice(0, 18)}…` : text;
  }
  if (item.kind === "document" && item.text?.trim()) return item.text.trim();
  return kindText(t, item.kind).label;
}

/** 能从一条线的末端长出来的种类。分组框不在其中 —— 它是个容器,不是一份产出。 */
export const SPAWNABLE_KINDS = ["image", "video", "audio", "note", "document"] as const;

/** 节点上方那一行:种类图标 + 名字(没起名是种类名)—— 一眼看出这格是什么,不用等它加载出来。
 *  双击改名,见 BoardNodeLabel。 */
function NodeLabel({ data, icon, fallback, secondary, className }: { data: BoardNodeData; icon?: LucideIcon; fallback?: string; secondary?: string; className?: string }) {
  const t = useI18n();
  const { item, renaming, commentMode, onRenaming, onRename } = data;
  return (
    <BoardNodeLabel
      icon={icon ?? kindIcon(item.kind)}
      title={item.title}
      fallback={fallback || kindText(t, item.kind).label}
      secondary={secondary}
      renaming={Boolean(renaming)}
      readOnly={commentMode}
      onRenaming={onRenaming && ((on) => onRenaming(on ? item.id : null))}
      onRename={onRename && ((title) => onRename(item.id, title))}
      className={className}
    />
  );
}

/**
 * 节点状态留在外壳和内容态里，不额外占用节点右上方。
 *
 * 排队、在跑、失败、取消各有一圈安静的外壳;**成功不留描边** —— 成功的证据是格子里的内容本身
 * (一张图、一段视频、右边新落下的几格)。此前成功后永远挂着一圈绿边,一张板生成过十几次就是
 * 十几圈绿框,反倒盖过画面。刚在眼前跑成功的那一下闪一次(useRunState),然后安静下来。
 */
const RUN_STATE_CLASS: Record<BoardItemRunStatus, string> = {
  idle: "ring-0",
  queued: "border-primary/45 ring-1 ring-primary/15",
  running:
    "border-primary/70 ring-2 ring-primary/25 shadow-[0_0_20px_color-mix(in_srgb,var(--primary)_16%,transparent)]",
  succeeded: "ring-0",
  failed: "border-destructive/75 ring-2 ring-destructive/25",
  cancelled: "border-dashed border-muted-foreground/60 opacity-80 ring-1 ring-muted-foreground/15",
};

/** 刚跑完时那一下的闪:这么久之后回到安静的外壳。 */
const SUCCESS_FLASH_MS = 1600;

/** 一格外壳上的运行态:`data-board-run-status` + 那一圈。**刚在眼前跑成功**的那一格闪一下再安静;
 *  打开画板时本来就成功着的不闪(那不是一件刚发生的事)。 */
function useRunState(item: BoardItem) {
  const status = itemRunStatus(item);
  const previous = React.useRef(status);
  const [flash, setFlash] = React.useState(false);
  React.useEffect(() => {
    const was = previous.current;
    previous.current = status;
    if (status !== "succeeded" || (was !== "running" && was !== "queued")) return;
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), SUCCESS_FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [status]);
  return {
    "data-board-run-status": status,
    "data-board-just-ran": flash ? "" : undefined,
    className: cn(RUN_STATE_CLASS[status], "transition-shadow duration-700", flash && "ring-2 ring-success/35"),
  } as const;
}

/**
 * 这一格在跑 / 跑挂了的时候怎么说。**按产出者说**:「生成失败」挂在一次截取或一个工具上是错话,
 * 「生成中」说一个翻译也不对。一张表,不按产出者名字逐个比 —— 工具格(`node:*`)一律是「运行」。
 * 没挂产出者的格子(贴进来的素材)照生成说。
 */
const RUN_COPY: Record<BuiltinProducer, { running: MessageKey; failed: MessageKey; stopHint?: MessageKey }> = {
  //: 远端的生成提交之后,供应商可能照样计费(ADR 0019)—— 停止键上说清楚。
  generate: { running: "generating", failed: "boardNodeGenerateFailed", stopHint: "boardStopMayCharge" },
  speak: { running: "generating", failed: "boardNodeGenerateFailed" },
  write: { running: "generating", failed: "boardNodeGenerateFailed" },
  trim: { running: "boardToolRunning", failed: "boardNodeRunFailed" },
};
const TOOL_RUN_COPY: { running: MessageKey; failed: MessageKey } = { running: "boardToolRunning", failed: "boardNodeRunFailed" };

function runCopy(item: BoardItem): { running: MessageKey; failed: MessageKey; stopHint?: MessageKey } {
  const producer = item.form?.producer;
  if (isNodeProducer(producer)) return TOOL_RUN_COPY;
  return RUN_COPY[(producer ?? "generate") as BuiltinProducer] ?? RUN_COPY.generate;
}

/**
 * 停止。**属于运行态的外壳,每一种在跑的格子都有** —— 此前只有工具格有,生成、念、写在跑时没有停的地方,
 * 虽然 `cancel_job` 对它们一样有效。点下去交给画布(BoardsView.stop → cancel_job),那一格的「已取消」
 * 由回执落回来。
 */
function StopButton({ item, onStop }: { item: BoardItem; onStop: (id: string) => void }) {
  const t = useI18n();
  const hint = runCopy(item).stopHint;
  return (
    <button
      type="button"
      data-board-stop=""
      title={hint ? t(hint) : undefined}
      className="nodrag nopan inline-flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded-md border border-border bg-panel px-2 text-ui-2xs text-foreground transition-colors hover:border-destructive hover:text-destructive"
      onClick={(event) => {
        event.stopPropagation();
        onStop(item.id);
      }}
    >
      <SquareIcon size={9} className="fill-current" /> {t("boardToolStop")}
    </button>
  );
}

/** 任务自己报的进度(0 到 1 之间)。任务没报就是 0 —— 不去猜一个数。 */
function useJobProgress(jobId: string | undefined, running: boolean): number {
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: running && Boolean(jobId),
    refetchInterval: running ? 2000 : false,
  });
  const progress = running ? (job.data?.progress ?? 0) : 0;
  return progress > 0 && progress < 1 ? progress : 0;
}

/** 便签:双击进入编辑。**单击不进** —— 单击是选中/拖动,想法摆位比改字更频繁。 */
export function NoteNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, onText, commentMode, workspaceId, boardId } = nodeData;
  const t = useI18n();
  const [editing, setEditing] = React.useState(false);
  const ref = React.useRef<HTMLTextAreaElement | null>(null);

  React.useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);

  const json = item.text_format === "json";
  const state = useRunState(item);
  const stop = nodeData.onStop && !commentMode && itemIsRunning(item) ? nodeData.onStop : undefined;
  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      className={cn(
        // **不在这一层 overflow-hidden。** 类型标签在框上方、接点在框左右两侧,都在框外 ——
        // 裁在这里等于把它们裁掉(图片/视频那两处已经栽过一次)。裁剪交给里面那层。
        "group relative h-full w-full rounded-xl border p-4 text-ui-md leading-relaxed shadow-sm transition-shadow",
        noteColorClass(item.color),
        state.className,
        //: 选中**不加彩色描边** —— 四角的缩放点已经说明选中了(图片/视频那两处早就这么做,
        //: 这里当时漏改)。便签本身是有颜色的,再套一圈主色就成了两种颜色打架。
      )}
      onDoubleClick={() => setEditing(true)}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <NodeLabel data={nodeData} />
      {selected && !editing && !commentMode && workspaceId && boardId && <div className="nodrag nowheel absolute right-0 top-full z-10 mt-2 whitespace-nowrap rounded-md bg-popover" onDoubleClick={e => e.stopPropagation()}><SaveToNote workspaceId={workspaceId} content={item.text || ""} sources={[{kind: "board", id: boardId, label: t("navBoards"), quote: item.text || ""}]} /></div>}
      <Ports visible={selected} disabled={commentMode} />
      {editing ? (
        //: **草稿式的框**(见 components/ui/draft-text):字住在 React Flow 的节点里,而 React Flow
        //: 在 effect 里才把它抄进自己的 store —— 直接 `value={item.text}` 的话每敲一下 React 都
        //: 先把框写回旧字,拼音组词被打断,字母直接上屏。
        <DraftTextarea
          ref={ref}
          // nodrag/nowheel:不挂的话在便签里选字会变成拖动整张便签,滚动会变成缩放画布。
          className={cn(
            "nodrag nowheel h-full w-full resize-none border-0 bg-transparent p-0 text-ui-sm leading-relaxed text-foreground outline-none",
            json && "font-mono text-ui-xs",
          )}
          value={item.text ?? ""}
          onValueChange={(next) => onText(item.id, next)}
          onBlur={() => setEditing(false)}
        />
      ) : (
        //: 工具格交回的结构化数据(JSON)按代码排版:等宽、能滚 —— 当成一段话排,
        //: 一份几十行的对象挤成一团,看不出层次。
        <div
          data-text-format={item.text_format}
          className={cn(
            "h-full w-full overflow-hidden whitespace-pre-wrap break-words text-foreground",
            json && "nowheel overflow-auto font-mono text-ui-xs leading-snug [overflow-wrap:anywhere]",
          )}
        >
          {item.text || <span className="text-muted-foreground">{t("boardNotePlaceholder")}</span>}
        </div>
      )}
      {stop && (
        <div className="absolute bottom-2 right-2">
          <StopButton item={item} onStop={stop} />
        </div>
      )}
    </div>
  );
}

/**
 * 还在跑的样子:整张卡按这一格的比例铺一层扫光占位,底下一行状态 —— 「生成中」/「正在运行」+ 进度
 * + 提示词摘要,右边是停止。
 *
 * **不是中间一个孤零零的小圈。** 此前是静止的灰底(调用处挂 `animate-none` 把占位的动画关了)
 * 加正中一个转圈,整张卡读起来像一块坏掉的灰板。扫光本身就说明"在动",状态落成字:
 * 减少动态时光停了,字还在。提示词让并行生成的多个空槽可以区分,只显示两行、允许任意长
 * URL 换行,不能撑破节点。
 *
 * 进度只写任务自己报了的(`job.progress` 在 0 和 1 之间)—— 不去猜一个数。生成、工具、念都是这一个样子。
 */
function Generating({ item, text, onStop }: { item: BoardItem; text?: string; onStop?: (id: string) => void }) {
  const t = useI18n();
  const progress = useJobProgress(itemJobId(item), itemIsRunning(item));
  return (
    <div role="status" aria-busy="true" className="relative h-full w-full overflow-hidden rounded-lg">
      <Skeleton className="absolute inset-0 h-full w-full rounded-lg" />
      {progress > 0 && (
        <div className="absolute inset-x-0 top-0 h-0.5 bg-primary/15">
          <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 flex min-w-0 max-w-full items-end gap-2 px-2.5 pb-2 pt-1.5 text-left">
        <div className="grid min-w-0 max-w-full flex-1 gap-0.5">
          <span className="text-ui-2xs font-semibold text-primary">
            {t(runCopy(item).running)}
            {progress > 0 ? ` · ${Math.round(progress * 100)}%` : ""}
          </span>
          {text ? (
            <span className="line-clamp-2 min-w-0 max-w-full [overflow-wrap:anywhere] text-ui-2xs leading-snug text-muted-foreground">
              {text}
            </span>
          ) : null}
        </div>
        {onStop && <StopButton item={item} onStop={onStop} />}
      </div>
    </div>
  );
}

function Queued({ item, text, onStop }: { item: BoardItem; text?: string; onStop?: (id: string) => void }) {
  const t = useI18n();
  return (
    <div className="relative grid h-full w-full place-items-center overflow-hidden rounded-lg bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-3">
      <div className="grid w-full min-w-0 max-w-full justify-items-center gap-1.5 text-center">
        <Clock3 size={16} className="text-primary" />
        <span className="text-ui-2xs font-medium text-primary">{t("boardNodeQueued")}</span>
        {text ? (
          <span className="line-clamp-3 min-w-0 max-w-full [overflow-wrap:anywhere] text-ui-2xs leading-relaxed text-muted-foreground">
            {text}
          </span>
        ) : null}
      </div>
      {onStop && (
        <div className="absolute bottom-2 right-2">
          <StopButton item={item} onStop={onStop} />
        </div>
      )}
    </div>
  );
}

/**
 * 跑挂了:任务结束了,没有产出。
 *
 * **不是转圈,也不是空槽。** 这两种此前都被拿来表示过失败,而两种都在骗人 —— 一个说"还在跑"
 * (于是用户一直等),一个说"你还没开始"(于是他以为自己点漏了)。原因写在框里:去任务中心
 * 翻一遍才知道为什么,对一个画布上的框来说太远了。
 *
 * **说的是「生成失败」/「运行失败」,不是「没能发起生成」** —— 任务明明发起了、跑到一半才挂;
 * 「没能发起」是提交那一刻被拒时的那句提示(BoardsView.RUN_FAILED),两件事。
 */
function Failed({ item, reason }: { item: BoardItem; reason: string }) {
  const t = useI18n();
  return (
    <div role="alert" className="grid h-full w-full place-items-center overflow-hidden rounded-lg bg-[color-mix(in_srgb,var(--destructive)_7%,transparent)] px-3">
      <div className="grid w-full min-w-0 max-w-full justify-items-center gap-1 text-center">
        <AlertTriangle size={15} className="text-destructive" />
        <span className="text-ui-2xs font-semibold text-destructive">{t(runCopy(item).failed)}</span>
        <span className="line-clamp-3 min-w-0 max-w-full [overflow-wrap:anywhere] text-ui-2xs leading-relaxed text-muted-foreground">
          {reason}
        </span>
      </div>
    </div>
  );
}

function Cancelled() {
  const t = useI18n();
  return (
    <div className="grid h-full w-full place-items-center overflow-hidden rounded-lg bg-secondary/35 px-3">
      <div className="grid justify-items-center gap-1 text-center text-muted-foreground">
        <Ban size={15} />
        <span className="text-ui-2xs font-semibold">{t("boardNodeCancelled")}</span>
      </div>
    </div>
  );
}

/**
 * 一格**还没有产出**时画什么:排队、在跑、跑挂了、取消了、空着。**运行态的外壳只此一处** ——
 * 图片、视频、音频格和工具格都走它,所以停止、进度、失败的说法在每一种格子上都一样。
 *
 * 此前三个媒体节点各写一份 `job_id ? 转圈 : 空槽`,工具格又自己写了一套在跑 / 跑挂了 ——
 * 状态从三种变成四种时,得记得每处都改;漏掉一处不会报错,只会是那一类节点永远转圈。
 */
function PendingSlot({ item, icon, hint, onStop }: { item: BoardItem; icon: React.ReactNode; hint?: string; onStop?: (id: string) => void }) {
  const status = itemRunStatus(item);
  const text = item.form?.prompt ?? item.text;
  const stop = onStop && itemIsRunning(item) ? onStop : undefined;
  if (status === "queued") return <Queued item={item} text={text} onStop={stop} />;
  if (status === "running") return <Generating item={item} text={text} onStop={stop} />;
  const error = itemError(item);
  if (status === "failed") return <Failed item={item} reason={error || "—"} />;
  if (status === "cancelled") return <Cancelled />;
  return <EmptySlot icon={icon} hint={hint} />;
}

/**
 * 空槽:还没写提示词、也没有任务。一块安静的占位,正中一枚淡淡的图标;缺东西时图标下面**至多一句**
 * (工具格的「接视频」)—— 别的都交给接点和连线去说。
 *
 * **不能画成转圈** —— 转圈的意思是"正在跑,等着就行",而这里等不来任何东西:它在等用户。
 * 两种状态长一样的话,用户会盯着一个永远不动的圈。也**不另套一圈虚线**:格子自己的实线边就是它的边,
 * 空和满是同一个框,空的只是里面安静。
 */
function EmptySlot({ icon, hint }: { icon: React.ReactNode; hint?: string }) {
  return (
    <div data-board-empty-slot="" className="grid h-full w-full place-items-center overflow-hidden text-muted-foreground/70">
      <div className="grid min-w-0 max-w-full justify-items-center gap-1 px-3 text-center">
        {icon}
        {hint ? (
          <span data-board-empty-hint="" className="line-clamp-1 min-w-0 max-w-full [overflow-wrap:anywhere] text-ui-2xs">
            {hint}
          </span>
        ) : null}
      </div>
    </div>
  );
}


/** 图片:指向素材库的一份。加载不出来时说清楚 —— 素材可能已经被删了。 */
export function ImageNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, onAspect, commentMode, onStop } = nodeData;
  const state = useRunState(item);

  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      className={cn(
        // **不在这一层 overflow-hidden。** 类型标签在框上方、接点在框左右两侧,都在框外 ——
        // 裁在这里会把它们切掉(工作流节点上刚犯过同一个错:「感叹号被截断了」)。
        // 圆角裁剪交给里面那层媒体。
        //: 边框一律安静的实线。选中**不加彩色描边** —— 四角的缩放点已经说明「选中了」,
        //: 再套一圈主色反而盖过节点里的画面。
        "group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm",
        state.className,
      )}
    >
      <NodeResizer minWidth={80} minHeight={60} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <NodeLabel data={nodeData} />
      <Ports visible={selected} disabled={commentMode} />
      {!item.asset_id ? (
        <PendingSlot item={item} icon={<ImageIcon size={20} />} onStop={commentMode ? undefined : onStop} />
      ) : (
        // 用仓库现成的预览件:它已经处理好**画布里必须关懒加载**这件事 ——
        // React Flow 的视口是 transform 过的,浏览器据此判断"还没进视野"而迟迟不发请求,
        // 图片就一直是 0×0,节点上看着像没产出。
        //: **不让它接管点击** —— 画布上点一下的意思是「选中这个节点」。被预览抢走之后,
        //: 操作条和表单都弹不出来。看大图走操作条上的「预览」。
        <AssetInlinePreview
          assetId={item.asset_id}
          name={item.text || ""}
          kind="image"
          plain
          previewOnClick={false}
          lazy={false}
          className="h-full w-full overflow-hidden rounded-lg object-cover"
          onNaturalSize={(width, height) => onAspect(item.id, width / height)}
        />
      )}
    </div>
  );
}

/**
 * 分组框:把相关的圈起来并命名。
 *
 * **只有边框和标题,中间是空的** —— 它要能盖在别的项下面当背景。所以 z 序上它永远在最底,
 * 而且中间不吃指针事件:不然框里的便签就点不中了。
 */
export function FrameNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item } = nodeData;
  const state = useRunState(item);

  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      className={cn(
        "group pointer-events-none relative h-full w-full rounded-xl border-2 border-dashed border-border-strong bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)]",
        selected && "border-primary",
        state.className,
      )}
    >
      {/* **手柄要自己把指针事件收回来。** 这个框整体是 pointer-events-none 的(见上:中间要让
          框里的项点得中),而 NodeResizer 的手柄和边线渲染在框**内部** —— 于是四角画得出来、
          拖不动,看着像坏了。标题栏早就是这么补的(下面那个 pointer-events-auto),手柄漏了。
          边线一并补上:它们透明但仍是拖拽热区,只有角能拉、边不能拉是同一个毛病挪了个位置。 */}
      <NodeResizer minWidth={160} minHeight={120} isVisible={selected} lineClassName="pointer-events-auto !border-transparent" handleClassName="pointer-events-auto !h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      {/* 只有标题吃指针事件 —— 拖它来移动整个框,框内区域让给里面的项(它是框唯一的抓手,
          所以不论这会儿能不能改名都收回指针事件)。**和别的节点同一个组件**(NodeLabel):框外正上方、同样的字号,
          名字也在同一个字段(title)—— 此前分组框的名字借住在 text 里,自己一枚输入框。 */}
      <NodeLabel data={nodeData} icon={Group} className="pointer-events-auto" />
    </div>
  );
}

/** 视频:就地播。**不自动播、不循环** —— 画板上可能同时摆着五段片子,一起动是噪音。 */
export function VideoNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, onAspect, commentMode, onStop } = nodeData;
  const state = useRunState(item);

  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      className={cn(
        // 同上:标签和接点都在框外,不能裁在这一层。
        //: 边框一律安静的实线。选中**不加彩色描边** —— 四角的缩放点已经说明「选中了」,
        //: 再套一圈主色反而盖过节点里的画面。
        "group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm",
        state.className,
      )}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <NodeLabel data={nodeData} />
      <Ports visible={selected} disabled={commentMode} />
      {!item.asset_id ? (
        <PendingSlot item={item} icon={<FilmIcon size={20} />} onStop={commentMode ? undefined : onStop} />
      ) : (
        // 自建播放器,不用原生 controls:那条控件不吃主题,而且它占掉的高度由浏览器说了算,
        // 会把按画面比例算好的框挤变形。nodrag 只挂在它的控件条上 —— 挂在整块上的话,
        // 鼠标一悬到视频上画布就拖不动了(踩过)。
        <BoardVideo
          assetId={item.asset_id}
          className="rounded-lg"
          onNaturalSize={(width, height) => onAspect(item.id, width / height)}
        />
      )}
    </div>
  );
}

/** 音频项。配音、旁白、BGM —— 摊在画板上的想法不该只有能看的。
 *  和图片/视频同一套三状态:空槽 / 生成中 / 有产出。 */
function AudioNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, commentMode, onStop } = nodeData;
  const state = useRunState(item);
  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      className={cn("group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm", state.className)}
    >
      <NodeResizer minWidth={200} minHeight={64} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <NodeLabel data={nodeData} />
      <Ports visible={selected} disabled={commentMode} />
      <div className="grid h-full w-full place-items-center overflow-hidden rounded-lg px-2">
        {!item.asset_id ? (
          <PendingSlot item={item} icon={<Music size={20} />} onStop={commentMode ? undefined : onStop} />
        ) : (
          <BoardAudio assetId={item.asset_id} />
        )}
      </div>
    </div>
  );
}


function DocumentNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const {
    item,
    document,
    commentMode,
    onPickDocument,
    onRefreshDocument,
    refreshingDocument,
  } = nodeData;
  const t = useI18n();
  const ref = document?.reference;
  const iconButton =
    "nodrag nopan inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-40";
  return (
    //: 选中**不加彩色描边** —— 四角的缩放点已经说明「选中了」(图片、视频、便签都是这一条)。
    <div className="group relative flex h-full w-full flex-col rounded-xl border border-border bg-panel shadow-sm">
      <NodeResizer
        minWidth={260}
        minHeight={200}
        isVisible={selected && !commentMode}
        lineClassName="!border-transparent"
        handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel"
      />
      <NodeLabel data={nodeData} />
      <Ports visible={selected} disabled={commentMode} />
      {/* 标题行只在**选了一篇笔记**之后出现,写的是那篇笔记的名字。还没选时它只会是第二个「文档」—— 格子上方的
          标签已经这么写了;那时整格就是一块安静的空状态,和空的图片格一样。 */}
      {item.note_id && (
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <BookOpen size={16} className="shrink-0 text-primary" />
        <span
          className="min-w-0 flex-1 truncate text-ui-sm font-medium"
          title={ref?.title || item.text}
        >
          {ref?.title || item.text || t("boardKindDocument")}
        </span>
        {!commentMode && (
          <button
            className={iconButton}
            title={t("documentReplace")}
            aria-label={t("documentReplace")}
            onClick={() => onPickDocument?.(item.id)}
          >
            <Replace size={14} />
          </button>
        )}
      </header>
      )}
      {!item.note_id ? (
        <button
          disabled={commentMode}
          className="nodrag nopan flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-5 text-center text-ui-xs text-muted-foreground transition-colors hover:bg-secondary/40"
          onClick={() => onPickDocument?.(item.id)}
        >
          <BookOpen size={28} strokeWidth={1.3} />
          <span className="font-medium text-foreground">
            {t("documentPick")}
          </span>
          <span>{t("documentEmptyHint")}</span>
        </button>
      ) : document?.pending ? (
        <div
          className="m-auto p-4 text-ui-xs text-muted-foreground"
          role="status"
        >
          {t("documentLoading")}
        </div>
      ) : document?.error ? (
        <div
          role="alert"
          className="m-auto p-4 text-center text-ui-xs text-muted-foreground"
        >
          {t("documentUnavailable")}
        </div>
      ) : (
        <div data-document-preview="" onDragStartCapture={(event) => event.preventDefault()} className="nowheel select-none min-h-0 flex-1 overflow-y-auto break-words px-4 py-3 text-ui-xs leading-relaxed text-foreground/85 [overflow-wrap:anywhere] [&_p]:my-2 [&_h1]:my-3 [&_h1]:text-base [&_h2]:my-3 [&_h2]:text-ui-sm [&_h2]:font-semibold [&_h3]:text-ui-sm [&_h3]:font-semibold [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-secondary [&_pre]:p-2 [&_img]:max-w-full [&_a]:text-primary [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3">
          <Streamdown mode="static" controls={false} className="pointer-events-none">
            {ref?.markdown.slice(0, 6000) || ""}
          </Streamdown>
          {(ref?.markdown.length ?? 0) > 6000 && (
            <p className="text-muted-foreground">…</p>
          )}
        </div>
      )}
      {item.note_id && (
        <footer className="flex shrink-0 items-center gap-2 border-t border-border px-3 py-2">
          <span
            title={t("documentPinned")}
            className="min-w-0 flex-1 text-ui-2xs text-muted-foreground"
          >
            v{item.note_revision}
          </span>
          {!commentMode && (
            <button
              className={iconButton}
              disabled={refreshingDocument}
              title={t("documentRefresh")}
              aria-label={t("documentRefresh")}
              onClick={() => onRefreshDocument?.(item.id)}
            >
              <RefreshCw
                size={14}
                className={refreshingDocument ? "animate-mosael-spin" : ""}
              />
            </button>
          )}
          <a
            className={iconButton}
            href={noteHref(item.note_id)}
            title={t("documentOpen")}
            aria-label={t("documentOpen")}
          >
            <ExternalLink size={14} />
          </a>
        </footer>
      )}
    </div>
  );
}

export function SceneNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, commentMode } = nodeData;
  const t = useI18n();
  const fallback = <div className="flex h-full flex-col items-center justify-center gap-2 bg-secondary/40 px-5 text-center text-muted-foreground"><Box size={32} strokeWidth={1.2} /><span className="text-ui-xs">{t(item.asset_id ? "boardScenePreviewMissing" : "boardScenePreviewEmpty")}</span></div>;
  //: `group`:接点在悬停时显形(group-hover)—— 少了它,3D 场景格的接点只有选中了才看得见。
  return <div className="group relative flex h-full w-full flex-col overflow-visible rounded-xl border border-border bg-panel shadow-sm">
    <NodeResizer minWidth={240} minHeight={180} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
    <NodeLabel data={nodeData} /><Ports visible={selected} disabled={commentMode} />
    <div className="min-h-0 flex-1 overflow-hidden rounded-t-xl">
      {item.asset_id ? <AssetInlinePreview key={item.asset_id} assetId={item.asset_id} name={item.text || ""} kind="image" plain previewOnClick={false} lazy={false} imageFallback={fallback} className="h-full w-full object-contain" /> : fallback}
    </div>
    <footer className="flex shrink-0 items-center gap-2 border-t border-border px-3 py-2">
      <Box size={15} className="shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate text-ui-sm" title={item.text}>{item.text || t("boardKindScene")}</span>
      <a className="nodrag nopan shrink-0 rounded-md border border-border bg-control px-2 py-1 text-ui-xs transition-colors hover:bg-secondary" href={`#/scenes?scene=${encodeURIComponent(item.scene_id ?? "")}`}>{t("boardSceneOpen")}</a>
    </footer>
  </div>;
}
/**
 * 工具格:跑一个插件工具或工作流节点。**它自己不放产出** —— 每跑一次,产出都新建成右边的几格、
 * 连上线(后端 canvas._derive),上一轮的留着。
 *
 * **它长得像它要产出的那种内容的空格子**(`tool.kind`,后端 `output_kinds` 的第一个):出图的工具是一块
 * 空的图片格,分离人声是一条空的音频格,翻译是一张空便签 —— 和旁边的内容格同一个外壳、同一个圆角、
 * 同一个正中淡淡的图标,只是那枚图标是这个工具自己的。名字在格子上方(插件工具在名字后面淡淡地写出处)。
 * 此前它是一张深色小卡:图标 + 两行说明 + 一张「吃什么 / 设置 / 产出」的小字表,看着像缩小的工作流节点,
 * 和画板上别的格子是两种语言。
 *
 * 格子里至多一句话:缺一样必填的输入时说「接视频」;输入的其余一切交给接点和连线。在跑、跑挂了、
 * 取消了和生成格同一个外壳(PendingSlot:扫光 + 进度 + 停止、失败写原因);跑完回到安静的空格子,
 * 产出在右边。表单挂在选中时的面板里(ActionComposer)。
 */
function ActionNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as BoardNodeData;
  const { item, commentMode, tool, onStop } = nodeData;
  const t = useI18n();
  const state = useRunState(item);
  const Icon = tool?.icon ?? kindIcon("action");
  const kind: ToolCellKind = tool?.kind ?? "image";
  //: 名字已经挂在框外正上方(没起名就是工具名);起了名之后,名字后面淡淡地写这是哪个工具。
  //: 插件工具点名出处 —— 它告诉你会用谁的服务;内置的不标。
  const renamed = Boolean(item.title?.trim());
  const secondary = [renamed ? tool?.label : "", tool?.plugin].filter(Boolean).join(" · ");
  const hint =
    tool === null
      ? t("boardToolUnavailableShort")
      : tool?.missing
        ? t("boardToolConnect").replace("{kinds}", eitherOf(t, tool.missing.map((one) => kindText(t, one).label)))
        : undefined;
  const slot = (
    <PendingSlot
      item={item}
      icon={tool === null ? <AlertTriangle size={20} /> : <Icon size={20} data-board-tool-icon="" />}
      hint={hint}
      onStop={commentMode ? undefined : onStop}
    />
  );
  return (
    <div
      data-board-run-status={state["data-board-run-status"]}
      data-board-action=""
      data-board-tool-kind={kind}
      //: 那一句说明悬停看 —— 格子上不再写字,它是一块内容的占位。
      title={tool?.description ? toPlainText(tool.description) : tool === null ? t("boardToolUnavailable") : undefined}
      className={cn(
        "group relative h-full w-full shadow-sm",
        //: **一律是空内容格那块中性的面板底**(见 ImageNode 的空槽),哪怕它产出的是一段字。便签的颜色只属于
        //: 真正的便签 —— 此前产出文字的工具格(翻译、转写)也涂成便签黄,放在画布上和一张真便签分不出来。
        //: 它会产出什么由正中的工具图标说,格子的形状(音频是一条)跟着产出的种类。
        "rounded-lg border border-border bg-panel",
        state.className,
      )}
    >
      <NodeResizer
        minWidth={kind === "audio" ? 200 : 120}
        minHeight={kind === "audio" ? 64 : 80}
        isVisible={selected}
        lineClassName="!border-transparent"
        handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel"
      />
      <NodeLabel data={nodeData} icon={Icon} fallback={tool?.label} secondary={secondary || undefined} />
      <Ports visible={selected} disabled={commentMode} />
      {kind === "audio" ? (
        <div className="grid h-full w-full place-items-center overflow-hidden rounded-lg px-2">{slot}</div>
      ) : (
        slot
      )}
    </div>
  );
}

/** 「A、B 或 C」。 */
function eitherOf(t: (key: MessageKey) => string, words: string[]): string {
  if (words.length < 2) return words[0] ?? "";
  return `${words.slice(0, -1).join(t("listSeparator"))}${t("boardToolKindsOr")}${words[words.length - 1]}`;
}

//: **写成 Record<kind, …> 而不是随手一个对象** —— 后端加一种 item kind 时,这里漏登记
//: 不会报错,只会让那种节点在画布上凭空消失。标上类型,漏一种就编译不过。
export const BOARD_NODE_TYPES: Record<BoardItem["kind"], React.ComponentType<NodeProps>> = {
  note: NoteNode,
  image: ImageNode,
  video: VideoNode,
  audio: AudioNode,
  frame: FrameNode,
  scene: SceneNode,
  document: DocumentNode,
  action: ActionNode,
};

/** 指向素材库一份的那几种。**只此一处** —— 操作条给不给「换一份」、选择器能选什么,
 *  都问它;分散判的话,加一种就会有一处忘记改(音频此前正是这么漏掉「换一份」的)。 */
export const MEDIA_KINDS = ["image", "video", "audio"] as const;
export type MediaKind = (typeof MEDIA_KINDS)[number];

export function isMediaKind(kind: string): kind is MediaKind {
  return (MEDIA_KINDS as readonly string[]).includes(kind);
}

/** 每种项新建时的默认大小。便签比图片矮 —— 它装的是一句话,不是一张图。 */
export const DEFAULT_SIZE: Record<BoardItem["kind"], { width: number; height: number }> = {
  note: { width: 220, height: 140 },
  image: { width: 260, height: 180 },
  video: { width: 320, height: 200 },
  audio: { width: 280, height: 72 },
  frame: { width: 420, height: 300 },
  scene: { width: 320, height: 220 },
  document: { width: 320, height: 300 },
  action: { width: 260, height: 180 },
};
