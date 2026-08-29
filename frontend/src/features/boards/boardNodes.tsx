import React from "react";
import { Handle, NodeResizer, Position, useStore, type NodeProps } from "@xyflow/react";
import { Film as FilmIcon, Image as ImageIcon, Loader2, Music, Plus, Square as SquareIcon, StickyNote, type LucideIcon } from "lucide-react";

import type { BoardItem } from "@/api/client";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { BoardAudio, BoardVideo } from "@/features/boards/BoardPlayer";
import { cn } from "@/lib/utils";

/**
 * 画板上的三种项。
 *
 * **和工作流节点分开写,不复用。** 两边看着都是"画布上的一个方块",但要的东西正相反:
 * 工作流节点表达的是**一个会执行的步骤**(有输入输出接点、有运行状态、有必填校验),
 * 画板上的东西表达的是**一个想法**(要能随手改大小、随手改颜色、双击就写字)。
 * 硬凑成一个组件的话,每加一个画板专属的交互都要先绕过工作流那套。
 */

/** 便签的色板。给固定几种而不是任意色值 —— 一组固定的色才让「黄色是待办、蓝色是参考」成立。 */
export const NOTE_COLORS = ["yellow", "blue", "green", "pink", "purple", "gray"] as const;
export type NoteColor = (typeof NOTE_COLORS)[number];

/** 每种颜色的底 / 边 / 字。用 color-mix 从主题色调出来,深浅主题各自成立。 */
const COLOR_CLASS: Record<NoteColor, string> = {
  yellow: "bg-[color-mix(in_srgb,#f5c518_18%,var(--panel))] border-[color-mix(in_srgb,#f5c518_45%,var(--border))]",
  blue: "bg-[color-mix(in_srgb,#3b82f6_16%,var(--panel))] border-[color-mix(in_srgb,#3b82f6_42%,var(--border))]",
  green: "bg-[color-mix(in_srgb,#22c55e_16%,var(--panel))] border-[color-mix(in_srgb,#22c55e_42%,var(--border))]",
  pink: "bg-[color-mix(in_srgb,#ec4899_15%,var(--panel))] border-[color-mix(in_srgb,#ec4899_40%,var(--border))]",
  purple: "bg-[color-mix(in_srgb,#8b5cf6_16%,var(--panel))] border-[color-mix(in_srgb,#8b5cf6_42%,var(--border))]",
  gray: "bg-[color-mix(in_srgb,var(--foreground)_7%,var(--panel))] border-border-strong",
};

export function noteColorClass(color: string | undefined): string {
  return COLOR_CLASS[(color as NoteColor) ?? "yellow"] ?? COLOR_CLASS.yellow;
}

/** 节点数据 = 画板项本身 + 一个回写文字的回调。React Flow 要求 data 是普通对象。 */
export type BoardNodeData = {
  item: BoardItem;
  onText: (id: string, text: string) => void;
  /** 媒体加载出来之后报一次自然宽高比 —— 节点据此把高度校正过来,画面才铺得满。 */
  onAspect: (id: string, ratio: number) => void;
};

/** 两侧各一个接点。**始终渲染但默认透明** —— 只在悬停/选中时显形:
 *  想法之间的关系是次要信息,一上来八个圆点会让画布看着像电路图。 */
/**
 * 左右两个接点。**画成圆形的 `+`**,选中或悬停时显形。
 *
 * 小圆点只说得出"这里能连线";而用户在画板上真正想做的是**从这一边接着往下长**(tapnow 同款)。
 * 一个 `+` 把这件事说清楚了,而它同时仍是 React Flow 的 Handle —— 拖它就是连线。
 *
 * 默认透明是因为想法之间的关系是次要信息:一上来每个节点四周都挂着圆圈,画布看着像电路图。
 */
function Ports({ visible }: { visible?: boolean }) {
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
  //: **锚点是 handle 在那一侧的外边缘,不是中心** —— 源码里 Position.Right 返回 x+width、
  //: Position.Left 返回 x。而默认样式把 handle 居中骑在边线上(translate ±50%),于是线头
  //: 天生就落在边外 width/2 处;handle 越大离得越远(横跨边线的大盒子那版差了 28px)。
  //: 把横向的位移抵掉,让方块整个缩进边内:左侧的左边缘、右侧的右边缘,就都正好压在边上。
  const flush = { transform: "translateY(-50%)" };
  const anchor = "!h-2 !w-2 !rounded-none !border-0 !bg-transparent !p-0 transition-opacity";
  const dot =
    "grid h-6 w-6 place-items-center rounded-full border border-border-strong bg-panel text-muted-foreground transition-colors hover:border-primary hover:text-primary";
  const shown = visible ? "opacity-100" : "opacity-0 group-hover:opacity-100";
  const scaled = (offset: number, origin: string) => ({
    transform: `scale(${1 / zoom}) translateX(${offset}px)`,
    transformOrigin: origin,
  });
  return (
    <>
      <Handle type="target" position={Position.Left} style={flush} className={cn(anchor, shown)}>
        <span className="absolute right-full top-1/2 -translate-y-1/2">
          <span className={dot} style={scaled(-10, "right center")}>
            <Plus size={13} />
          </span>
        </span>
      </Handle>
      <Handle type="source" position={Position.Right} style={flush} className={cn(anchor, shown)}>
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
export const KIND_META: Record<BoardItem["kind"], { icon: LucideIcon; label: string; hint: string }> = {
  note: { icon: StickyNote, label: "便签", hint: "写一段想法、脚本或提示词" },
  image: { icon: ImageIcon, label: "图片", hint: "生成或贴一张图" },
  video: { icon: FilmIcon, label: "视频", hint: "生成或贴一段视频" },
  audio: { icon: Music, label: "音频", hint: "配音、旁白、背景音乐" },
  frame: { icon: SquareIcon, label: "分组", hint: "把一堆东西圈起来命名" },
};

/** 能从一条线的末端长出来的种类。分组框不在其中 —— 它是个容器,不是一份产出。 */
export const SPAWNABLE_KINDS = ["image", "video", "audio", "note"] as const;

/** 节点上方那行类型标签 —— 一眼看出这格是图片还是视频,不用等它加载出来。 */
function TypeLabel({ kind }: { kind: BoardItem["kind"] }) {
  const { icon: Icon, label } = KIND_META[kind];
  return (
    <span className="pointer-events-none absolute -top-5 left-0 inline-flex items-center gap-1 text-ui-2xs text-muted-foreground">
      <Icon size={11} /> {label}
    </span>
  );
}

/** 便签:双击进入编辑。**单击不进** —— 单击是选中/拖动,想法摆位比改字更频繁。 */
export function NoteNode({ data, selected }: NodeProps) {
  const { item, onText } = data as unknown as BoardNodeData;
  const [editing, setEditing] = React.useState(false);
  const ref = React.useRef<HTMLTextAreaElement | null>(null);

  React.useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);

  return (
    <div
      className={cn(
        // **不在这一层 overflow-hidden。** 类型标签在框上方、接点在框左右两侧,都在框外 ——
        // 裁在这里等于把它们裁掉(图片/视频那两处已经栽过一次)。裁剪交给里面那层。
        "group relative h-full w-full rounded-lg border p-2.5 text-ui-sm leading-relaxed shadow-sm transition-shadow",
        noteColorClass(item.color),
        selected && "ring-2 ring-primary",
      )}
      onDoubleClick={() => setEditing(true)}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <TypeLabel kind="note" />
      <Ports visible={selected} />
      {editing ? (
        <textarea
          ref={ref}
          // nodrag/nowheel:不挂的话在便签里选字会变成拖动整张便签,滚动会变成缩放画布。
          className="nodrag nowheel h-full w-full resize-none border-0 bg-transparent p-0 text-ui-sm leading-relaxed text-foreground outline-none"
          value={item.text ?? ""}
          onChange={(event) => onText(item.id, event.target.value)}
          onBlur={() => setEditing(false)}
        />
      ) : (
        <div className="h-full w-full overflow-hidden whitespace-pre-wrap break-words text-foreground">
          {item.text || <span className="text-muted-foreground">双击写点什么</span>}
        </div>
      )}
    </div>
  );
}

/**
 * 还在生成的样子:转圈 + 那句提示词。
 *
 * **要看得见提示词**。画布上同时跑三四个生成时,四个一模一样的转圈框分不出谁是谁 ——
 * 而用户想撤掉的往往正是其中某一个。
 */
function Generating({ text }: { text?: string }) {
  return (
    <div className="grid h-full w-full place-items-center gap-1.5 px-3 text-center">
      <Loader2 size={16} className="animate-spin text-primary" />
      {text ? <span className="line-clamp-3 text-ui-2xs leading-relaxed text-muted-foreground">{text}</span> : null}
    </div>
  );
}

/**
 * 空槽:还没写提示词、也没有任务。
 *
 * **不能画成转圈** —— 转圈的意思是"正在跑,等着就行",而这里等不来任何东西:它在等用户写字。
 * 两种状态长一样的话,用户会盯着一个永远不动的圈。
 */
function EmptySlot({ icon }: { icon: React.ReactNode }) {
  //: 虚线由**节点自己**画(见下面各节点的 emptyRing),这里只放图标 —— 两层虚线套在一起
  //: 会露出两圈错开的边。
  return <div className="grid h-full w-full place-items-center text-muted-foreground/70">{icon}</div>;
}


/** 图片:指向素材库的一份。加载不出来时说清楚 —— 素材可能已经被删了。 */
export function ImageNode({ data, selected }: NodeProps) {
  const { item, onAspect } = data as unknown as BoardNodeData;

  return (
    <div
      className={cn(
        // **不在这一层 overflow-hidden。** 类型标签在框上方、接点在框左右两侧,都在框外 ——
        // 裁在这里会把它们切掉(工作流节点上刚犯过同一个错:「感叹号被截断了」)。
        // 圆角裁剪交给里面那层媒体。
        //: 边框一律安静的实线。选中**不加彩色描边** —— 四角的缩放点已经说明「选中了」,
        //: 再套一圈主色反而盖过节点里的画面。
        "group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm",
      )}
    >
      <NodeResizer minWidth={80} minHeight={60} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <TypeLabel kind="image" />
      <Ports visible={selected} />
      {!item.asset_id ? (
        item.job_id ? <Generating text={item.text} /> : <EmptySlot icon={<ImageIcon size={20} />} />
      ) : (
        // 用仓库现成的预览件:它已经处理好**画布里必须关懒加载**这件事 ——
        // React Flow 的视口是 transform 过的,浏览器据此判断"还没进视野"而迟迟不发请求,
        // 图片就一直是 0×0,节点上看着像没产出。
        <AssetInlinePreview
          assetId={item.asset_id}
          name={item.text || ""}
          kind="image"
          plain
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
  const { item, onText } = data as unknown as BoardNodeData;
  const [editing, setEditing] = React.useState(false);

  return (
    <div
      className={cn(
        "group pointer-events-none relative h-full w-full rounded-xl border-2 border-dashed border-border-strong bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)]",
        selected && "border-primary",
      )}
    >
      <NodeResizer minWidth={160} minHeight={120} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      {/* 只有标题条吃指针事件 —— 拖它来移动整个框,框内区域让给里面的项。 */}
      <div className="pointer-events-auto absolute -top-0.5 left-2 flex max-w-[90%] -translate-y-1/2 items-center rounded-md border border-border bg-panel px-2 py-0.5">
        {editing ? (
          <input
            autoFocus
            className="nodrag w-40 border-0 bg-transparent p-0 text-ui-2xs font-medium text-foreground outline-none"
            value={item.text ?? ""}
            onChange={(event) => onText(item.id, event.target.value)}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <span
            className="cursor-text truncate text-ui-2xs font-medium text-muted-foreground"
            onDoubleClick={() => setEditing(true)}
          >
            {item.text || "分组"}
          </span>
        )}
      </div>
    </div>
  );
}

/** 视频:就地播。**不自动播、不循环** —— 画板上可能同时摆着五段片子,一起动是噪音。 */
export function VideoNode({ data, selected }: NodeProps) {
  const { item, onAspect } = data as unknown as BoardNodeData;

  return (
    <div
      className={cn(
        // 同上:标签和接点都在框外,不能裁在这一层。
        //: 边框一律安静的实线。选中**不加彩色描边** —— 四角的缩放点已经说明「选中了」,
        //: 再套一圈主色反而盖过节点里的画面。
        "group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm",
      )}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <TypeLabel kind="video" />
      <Ports visible={selected} />
      {!item.asset_id ? (
        item.job_id ? <Generating text={item.text} /> : <EmptySlot icon={<FilmIcon size={20} />} />
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
  const { item } = data as unknown as BoardNodeData;
  return (
    <div className="group relative h-full w-full rounded-lg border border-border bg-panel shadow-sm">
      <NodeResizer minWidth={200} minHeight={64} isVisible={selected} lineClassName="!border-transparent" handleClassName="!h-2 !w-2 !rounded-full !border-border-strong !bg-panel" />
      <TypeLabel kind="audio" />
      <Ports visible={selected} />
      <div className="grid h-full w-full place-items-center overflow-hidden rounded-lg px-2">
        {!item.asset_id ? (
          item.job_id ? <Generating text={item.text} /> : <EmptySlot icon={<Music size={20} />} />
        ) : (
          <BoardAudio assetId={item.asset_id} />
        )}
      </div>
    </div>
  );
}

//: **写成 Record<kind, …> 而不是随手一个对象** —— 后端加一种 item kind 时,这里漏登记
//: 不会报错,只会让那种节点在画布上凭空消失。标上类型,漏一种就编译不过。
export const BOARD_NODE_TYPES: Record<BoardItem["kind"], React.ComponentType<NodeProps>> = {
  note: NoteNode,
  image: ImageNode,
  video: VideoNode,
  audio: AudioNode,
  frame: FrameNode,
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
};
