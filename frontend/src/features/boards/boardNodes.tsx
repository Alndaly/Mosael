import React from "react";
import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import { Film as FilmIcon, Image as ImageIcon, Loader2 } from "lucide-react";

import { API_BASE, type BoardItem } from "@/api/client";
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
};

/** 两侧各一个接点。**始终渲染但默认透明** —— 只在悬停/选中时显形:
 *  想法之间的关系是次要信息,一上来八个圆点会让画布看着像电路图。 */
function Ports() {
  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-border-strong !bg-panel opacity-0 transition-opacity group-hover:opacity-100"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-border-strong !bg-panel opacity-0 transition-opacity group-hover:opacity-100"
      />
    </>
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
        "group relative h-full w-full overflow-hidden rounded-lg border p-2.5 text-ui-sm leading-relaxed shadow-sm transition-shadow",
        noteColorClass(item.color),
        selected && "ring-2 ring-primary",
      )}
      onDoubleClick={() => setEditing(true)}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-primary" handleClassName="!h-2 !w-2 !rounded-sm !border-primary !bg-panel" />
      <Ports />
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
        <div className="h-full w-full whitespace-pre-wrap break-words text-foreground">
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
  return (
    <div className="grid h-full w-full place-items-center rounded-lg border border-dashed border-border-strong text-muted-foreground">
      {icon}
    </div>
  );
}

/** 图片:指向素材库的一份。加载不出来时说清楚 —— 素材可能已经被删了。 */
export function ImageNode({ data, selected }: NodeProps) {
  const { item } = data as unknown as BoardNodeData;
  const [broken, setBroken] = React.useState(false);

  return (
    <div
      className={cn(
        "group relative h-full w-full overflow-hidden rounded-lg border border-border bg-panel shadow-sm",
        selected && "ring-2 ring-primary",
      )}
    >
      <NodeResizer minWidth={80} minHeight={60} isVisible={selected} lineClassName="!border-primary" handleClassName="!h-2 !w-2 !rounded-sm !border-primary !bg-panel" />
      <Ports />
      {!item.asset_id ? (
        item.job_id ? <Generating text={item.text} /> : <EmptySlot icon={<ImageIcon size={20} />} />
      ) : broken ? (
        <div className="grid h-full w-full place-items-center px-3 text-center text-ui-2xs text-muted-foreground">
          这份素材已经不在了
        </div>
      ) : (
        <img
          src={`${API_BASE}/api/assets/${item.asset_id}/file`}
          alt={item.text || ""}
          // 拖不动整块的话用户会以为图片卡住了 —— 图片自己不接收拖拽。
          draggable={false}
          className="h-full w-full object-cover"
          onError={() => setBroken(true)}
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
      <NodeResizer minWidth={160} minHeight={120} isVisible={selected} lineClassName="!border-primary" handleClassName="!h-2 !w-2 !rounded-sm !border-primary !bg-panel" />
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
  const { item } = data as unknown as BoardNodeData;
  const [broken, setBroken] = React.useState(false);

  return (
    <div
      className={cn(
        "group relative h-full w-full overflow-hidden rounded-lg border border-border bg-panel shadow-sm",
        selected && "ring-2 ring-primary",
      )}
    >
      <NodeResizer minWidth={120} minHeight={80} isVisible={selected} lineClassName="!border-primary" handleClassName="!h-2 !w-2 !rounded-sm !border-primary !bg-panel" />
      <Ports />
      {!item.asset_id ? (
        item.job_id ? <Generating text={item.text} /> : <EmptySlot icon={<FilmIcon size={20} />} />
      ) : broken ? (
        <div className="grid h-full w-full place-items-center px-3 text-center text-ui-2xs text-muted-foreground">
          这份素材已经不在了
        </div>
      ) : (
        <video
          src={`${API_BASE}/api/assets/${item.asset_id}/file`}
          controls
          preload="metadata"
          // nodrag/nowheel:不挂的话拖进度条会变成拖动整个节点,滚轮会缩放画布。
          className="nodrag nowheel h-full w-full bg-black object-contain"
          onError={() => setBroken(true)}
        />
      )}
    </div>
  );
}

export const BOARD_NODE_TYPES = { note: NoteNode, image: ImageNode, video: VideoNode, frame: FrameNode };

/** 每种项新建时的默认大小。便签比图片矮 —— 它装的是一句话,不是一张图。 */
export const DEFAULT_SIZE: Record<BoardItem["kind"], { width: number; height: number }> = {
  note: { width: 220, height: 140 },
  image: { width: 260, height: 180 },
  video: { width: 320, height: 200 },
  frame: { width: 420, height: 300 },
};
