import React from "react";

import { listenKeys } from "@/lib/shortcuts";
import { createPortal } from "react-dom";
import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";
import {
  Handle,
  Position,
  useStore,
  type Edge,
  type FinalConnectionState,
  type Node,
  type NodeProps,
  type XYPosition,
} from "@xyflow/react";
import type { LucideIcon } from "lucide-react";

import { CANVAS_EDGE_MARKER, CANVAS_PENDING_EDGE_STYLE, type EdgeShape } from "@/components/app/canvasEdgeShape";
import { FLOATING_COLLISION_PADDING, FLOATING_SURFACE, MENU_ITEM } from "@/components/ui/floating";
import { cn } from "@/lib/utils";

/**
 * 「从节点拉出一根线、松手在空白处 → 选一种,就地长出下一格」这件事的**画布那一半**。
 *
 * 节点编辑器的通行做法(tldraw / Figma / n8n 都是这样):松手的地方先摆一个**虚线占位**,
 * 线从起手的接点连到占位的接点上,旁边挂一张单子。此前画板只画了一根跟实线长得不一样的
 * 细灰线,线头悬在半空,单子孤零零地浮在旁边 —— 用户看不出新的一格会落在哪、有多大。
 *
 * 三条规矩,都是这个交互成立的前提:
 *
 *  · **占位就是将来那一格的位置和大小。** 摆放规则只有 `ghostRect` 这一处,真正建节点时
 *    也照它算 —— 两边各算一份的话,选完那一下节点会跳一下,占位就成了骗人的。
 *    单子上高亮哪一种,占位就换成哪一种的大小:落点那一侧的边始终钉在松手点上,线头不动。
 *  · **占位和待定的线只活在「画出来的那一份」里。** 它们由 `decorate` 在渲染时贴到节点/连线
 *    数组末尾,不进画布状态 —— 于是不会被自动保存带到服务端,也不会在撤销历史里留下一步
 *    「多了个占位」。选中一种时建的是真节点 + 真连线,一次状态变更,历史里正好一步。
 *  · **待定的线就是一条真的 React Flow 边。** 同一个边组件、同一种走线(贝塞尔/折线跟着
 *    画布的偏好)、同一个箭头,只是虚线 + 主色表示「还没定」。自己拿 getBezierPath 画一根
 *    的话,样式、走线、端点每一样都得和真边对齐一遍,而上一版就是没对齐。
 *
 * 工作流编辑器目前没有「松手在空白处」这条路;哪天要加,用的也是这一份。
 */

/** 占位节点 / 待定连线的 id。带前缀下划线,不会和任何真节点撞。 */
export const PENDING_GHOST_ID = "__pending-link-ghost";
export const PENDING_EDGE_ID = "__pending-link-edge";
/** 占位节点的类型名 —— 画布的 nodeTypes 里要登记它(见 PENDING_LINK_NODE_TYPES)。 */
export const PENDING_GHOST_TYPE = "pendingLinkGhost";

/** 松手那一刻定下来的事实。只有这些 —— 占位多大取决于单子上高亮的是哪一种,不在这里。 */
export interface PendingLink {
  /** 从哪一格拉出来的。 */
  nodeId: string;
  /** 起手的那个接点(画板的接点没有 id,工作流有)。 */
  handleId: string | null;
  /** 从出口(source)拉出来的:新的一格接在它后面;从入口拉出来的:接在它前面。 */
  fromSource: boolean;
  /** 松手点,流坐标。 */
  at: XYPosition;
}

export interface Size {
  width: number;
  height: number;
}

/**
 * 新的一格摆在哪、占多大。**占位和真节点都照它算,只此一处。**
 *
 * 从出口拉出来的,新格的**左边中点**落在松手点(线从左边接进去);从入口拉出来的,**右边
 * 中点**落在松手点(线从右边接出来)。于是换一种大小时,线头那一端纹丝不动。
 */
export function ghostRect(at: XYPosition, size: Size, fromSource: boolean): XYPosition & Size {
  return {
    x: Math.round(at.x - (fromSource ? 0 : size.width)),
    y: Math.round(at.y - size.height / 2),
    width: size.width,
    height: size.height,
  };
}

/**
 * 从 React Flow 的 onConnectEnd 里读出「松手在空白处」。连到了别的接点上(isValid)就不是 ——
 * 那是一次正常连线,已经由 onConnect 接住了。
 */
export function pendingLinkFromRelease(
  event: MouseEvent | TouchEvent,
  state: FinalConnectionState,
  screenToFlowPosition: (point: XYPosition) => XYPosition,
): PendingLink | null {
  if (state.isValid || !state.fromNode || !state.fromHandle) return null;
  const point = "changedTouches" in event ? event.changedTouches[0] : event;
  if (!point) return null;
  return {
    nodeId: state.fromNode.id,
    handleId: state.fromHandle.id ?? null,
    fromSource: state.fromHandle.type !== "target",
    at: screenToFlowPosition({ x: point.clientX, y: point.clientY }),
  };
}

/** 单子上的一种。图标、名字、一句说明 —— 由各画布自己给(它们各有各的节点种类)。 */
export interface PendingLinkOption {
  icon: LucideIcon;
  label: string;
  hint?: string;
}

type GhostData = { icon: LucideIcon; label: string };

/**
 * 占位节点。虚线描边 + 一层很淡的主色底 + 中间一枚图标,上方一行和真节点同款的类型标签。
 *
 * **它跟着画布缩放**(它就是将来那一格,拉远了自然也该小);只有上方那行字反着缩放,
 * 和真节点的类型标签一样在屏幕上保持一个字号。接点是两个看不见的贴边小方块 ——
 * 待定的线要有地方接,但这里不该再冒出两个能拖的 `+`。
 */
export function PendingLinkGhost({ data }: NodeProps) {
  const { icon: Icon, label } = data as unknown as GhostData;
  const zoom = useStore((state) => state.transform[2]) || 1;
  //: 接点贴在边上、不居中骑线 —— 锚点取的是接点那一侧的外边缘(见画板 Ports 的说明)。
  const flush = { transform: "translateY(-50%)" };
  const anchor = "!h-2 !w-2 !min-h-0 !min-w-0 !rounded-none !border-0 !bg-transparent !p-0 !opacity-0";
  return (
    <div
      data-pending-link-ghost=""
      aria-hidden
      className="relative grid h-full w-full place-items-center rounded-xl border-[1.5px] border-dashed border-primary/70 bg-[color-mix(in_oklab,var(--primary)_9%,transparent)] text-primary"
    >
      <span
        className="pointer-events-none absolute bottom-full left-0 inline-flex origin-bottom-left items-center gap-1 whitespace-nowrap pb-1 text-ui-2xs text-primary"
        style={{ transform: `scale(${1 / zoom})` }}
      >
        <Icon size={11} /> {label}
      </span>
      <span className="grid h-10 w-10 place-items-center rounded-full border border-dashed border-primary/50 bg-panel/80">
        <Icon size={18} />
      </span>
      <Handle type="target" position={Position.Left} isConnectable={false} style={flush} className={anchor} />
      <Handle type="source" position={Position.Right} isConnectable={false} style={flush} className={anchor} />
    </div>
  );
}

/** 挂进画布 nodeTypes 的那一项。 */
export const PENDING_LINK_NODE_TYPES = { [PENDING_GHOST_TYPE]: PendingLinkGhost } as const;

/**
 * 把占位和待定的线贴到**画出来的那一份**末尾。没有待定时原样返回(不换引用)。
 *
 * 起手那一格已经不在了(别处删了它、服务端那份换进来)就什么都不贴 —— 一根一头悬空的线
 * 比没有更糟。调用方同时该把待定取消掉。
 */
export function decoratePendingLink<N extends Node, E extends Edge>(
  nodes: N[],
  edges: E[],
  link: PendingLink | null,
  ghost: { size: Size; option: PendingLinkOption; shape: EdgeShape; zIndex?: number },
): { nodes: N[]; edges: E[] } {
  if (!link || !nodes.some((node) => node.id === link.nodeId)) return { nodes, edges };
  const rect = ghostRect(link.at, ghost.size, link.fromSource);
  const ghostNode = {
    id: PENDING_GHOST_ID,
    type: PENDING_GHOST_TYPE,
    position: { x: rect.x, y: rect.y },
    width: rect.width,
    height: rect.height,
    //: **尺寸和接点都直接给上,不等 React Flow 去量。** 它量完是经 onNodesChange 回写到画布
    //: 状态里的 —— 而占位不在状态里,量出来的东西没处落,下一轮渲染它又是一个「没量过」的
    //: 节点(xyflow 见 measured 为空会把接点位置清掉),于是那根待定的线永远画不出来。
    //: 接点是两个贴边的 8px 方块,和 PendingLinkGhost 里画的那两个一致。
    measured: { width: rect.width, height: rect.height },
    handles: [
      { type: "target", position: Position.Left, x: 0, y: rect.height / 2 - 4, width: 8, height: 8 },
      { type: "source", position: Position.Right, x: rect.width - 8, y: rect.height / 2 - 4, width: 8, height: 8 },
    ],
    data: { icon: ghost.option.icon, label: ghost.option.label } satisfies GhostData,
    draggable: false,
    selectable: false,
    connectable: false,
    focusable: false,
    deletable: false,
    zIndex: ghost.zIndex,
  } as unknown as N;
  const edge = {
    id: PENDING_EDGE_ID,
    ...(link.fromSource
      ? { source: link.nodeId, sourceHandle: link.handleId, target: PENDING_GHOST_ID, targetHandle: null }
      : { source: PENDING_GHOST_ID, sourceHandle: null, target: link.nodeId, targetHandle: link.handleId }),
    type: ghost.shape,
    selectable: false,
    focusable: false,
    deletable: false,
    style: CANVAS_PENDING_EDGE_STYLE,
    markerEnd: { ...CANVAS_EDGE_MARKER, color: "var(--primary)" },
    data: { pending: true },
  } as unknown as E;
  return { nodes: [...nodes, ghostNode], edges: [...edges, edge] };
}

/**
 * 一次待定连线的全部状态:松手点、单子上高亮的是哪一种、开关。
 *
 * `kinds` 的顺序就是单子的顺序;打开时高亮第一种,占位也先是它的大小。
 */
export function usePendingLink<K extends string>({
  kinds,
  sizeOf,
  describe,
  onChoose,
}: {
  kinds: readonly K[];
  sizeOf: (kind: K) => Size;
  describe: (kind: K) => PendingLinkOption;
  /** 选定了一种。建节点、连线由调用方做 —— 位置照 `ghostRect(link.at, sizeOf(kind), link.fromSource)`。 */
  onChoose: (kind: K, link: PendingLink) => void;
}) {
  const [link, setLink] = React.useState<PendingLink | null>(null);
  const [active, setActive] = React.useState(0);
  const kind = kinds[Math.min(active, kinds.length - 1)];

  const open = React.useCallback((next: PendingLink) => {
    setActive(0);
    setLink(next);
  }, []);
  const cancel = React.useCallback(() => setLink(null), []);
  const choose = React.useCallback(
    (picked: K) => {
      if (!link) return;
      setLink(null);
      onChoose(picked, link);
    },
    [link, onChoose],
  );

  const decorate = React.useCallback(
    <N extends Node, E extends Edge>(nodes: N[], edges: E[], shape: EdgeShape, zIndex?: number) =>
      decoratePendingLink(nodes, edges, link, { size: sizeOf(kind), option: describe(kind), shape, zIndex }),
    [link, kind, sizeOf, describe],
  );

  return { link, active, setActive, kind, open, cancel, choose, decorate };
}

/**
 * 挂在占位旁边的那张单子。
 *
 * · **贴着占位摆**:从出口拉出来的摆在占位右边,从入口拉出来的摆在左边(都是「往外长」的
 *   那一侧,不会压在起手那一格和那根线上);放不下就挪到占位下面、再不行上面,最后才翻到
 *   另一侧,并贴边挪进窗口。
 *   位置交给 floating-ui,每帧跟着占位的真实矩形走。
 * · **键盘走得通**:打开就把焦点放在第一项上;↑↓(Home/End)换高亮,回车选定,Esc 取消。
 *   取消时焦点还给打开前的那个元素;选定时不还 —— 新的那一格会被选中、挂上它的面板。
 * · **点别处、拖画布就取消**:用 document 上的 pointerdown 听,而不是铺一层透明遮罩 ——
 *   遮罩会把那一下拖动吃掉,用户得拖第二次画布才动。
 */
export function PendingLinkMenu<K extends string>({
  title,
  kinds,
  describe,
  active,
  onActiveChange,
  onChoose,
  onCancel,
  fromSource,
  anchor,
}: {
  title: string;
  kinds: readonly K[];
  describe: (kind: K) => PendingLinkOption;
  active: number;
  onActiveChange: (index: number) => void;
  onChoose: (kind: K) => void;
  onCancel: () => void;
  fromSource: boolean;
  /** 占位节点的 DOM。每帧现取 —— 缩放、换大小之后它的矩形都会变。 */
  anchor: () => Element | null;
}) {
  const menuEl = React.useRef<HTMLDivElement>(null);
  const items = React.useRef<(HTMLButtonElement | null)[]>([]);
  const anchorRef = React.useRef(anchor);
  anchorRef.current = anchor;
  const cancelRef = React.useRef(onCancel);
  cancelRef.current = onCancel;
  //: 选定之后不把焦点还回去 —— 见上面的说明。
  const chosen = React.useRef(false);

  React.useLayoutEffect(() => {
    const floating = menuEl.current;
    if (!floating) return;
    let alive = true;
    let lastRect: DOMRect | null = null;
    //: 占位节点和单子同一轮挂上,但 React Flow 量完尺寸前它的矩形可能还是空的 —— 沿用上一帧的。
    const reference = {
      getBoundingClientRect: () => {
        const rect = anchorRef.current()?.getBoundingClientRect();
        if (rect && rect.width > 0 && rect.height > 0) lastRect = rect;
        return lastRect ?? rect ?? new DOMRect();
      },
    };
    const side = fromSource ? "right" : "left";
    const stop = autoUpdate(reference, floating, () => {
      void computePosition(reference, floating, {
        strategy: "fixed",
        placement: `${side}-start`,
        middleware: [
          offset(12),
          //: 放不下时先上下、最后才翻到另一侧 —— 另一侧正是起手那一格和待定的线所在,
          //: 翻过去就把线盖住了。
          flip({
            fallbackPlacements: fromSource ? ["bottom-start", "top-start", "left-start"] : ["bottom-end", "top-end", "right-start"],
            //: 只在左右放不下时才换位置;上下差一点交给 shift 往里挪 —— 否则占位靠近窗口底边时,
            //: 单子会为了几个像素整个跳到占位上面,盖住起手那一格。
            crossAxis: false,
            padding: FLOATING_COLLISION_PADDING,
          }),
          shift({ padding: FLOATING_COLLISION_PADDING, crossAxis: true }),
        ],
      }).then(({ x, y }) => {
        if (!alive) return;
        Object.assign(floating.style, { left: `${x}px`, top: `${y}px`, opacity: "1" });
      });
    }, { animationFrame: true });
    return () => {
      alive = false;
      stop();
    };
  }, [fromSource]);

  //: 打开时把焦点收进来,关掉时(取消的话)还回去。
  React.useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    items.current[0]?.focus({ preventScroll: true });
    return () => {
      if (!chosen.current && previous?.isConnected && previous !== document.body) previous.focus({ preventScroll: true });
    };
  }, []);

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      cancelRef.current();
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target instanceof Node ? event.target : null;
      if (target && (menuEl.current?.contains(target) || anchorRef.current()?.contains(target))) return;
      cancelRef.current();
    };
    const stopKeys = listenKeys(window, onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      stopKeys();
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, []);

  const move = (index: number) => {
    const next = (index + kinds.length) % kinds.length;
    onActiveChange(next);
    items.current[next]?.focus({ preventScroll: true });
  };

  return createPortal(
    <div
      ref={menuEl}
      role="menu"
      aria-label={title}
      data-pending-link-menu=""
      //: 摆好位置之前先透明 —— **不能用 visibility: hidden**:隐藏的元素拿不到焦点,打开时
      //: 往第一项上放的焦点会落空,键盘就用不了(真机上焦点留在了起手那一格上)。
      style={{ opacity: 0 }}
      className={cn(FLOATING_SURFACE, "fixed left-0 top-0 z-50 w-60 p-1.5")}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" || (event.key === "Tab" && !event.shiftKey)) move(active + 1);
        else if (event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey)) move(active - 1);
        else if (event.key === "Home") move(0);
        else if (event.key === "End") move(kinds.length - 1);
        //: 回车/空格自己接,不等按钮的原生 click:焦点万一没落在按钮上(比如被别处抢走又
        //: 还回到菜单容器),原生那条就不会触发,而高亮的那一项是明确的。
        else if ((event.key === "Enter" || event.key === "Space" || event.key === " ") && !event.nativeEvent.isComposing) {
          chosen.current = true;
          onChoose(kinds[active]);
        } else return;
        event.preventDefault();
      }}
    >
      <p className="px-2.5 pb-1 pt-1.5 text-ui-2xs text-muted-foreground">{title}</p>
      {kinds.map((kind, index) => {
        const { icon: Icon, label, hint } = describe(kind);
        const highlighted = index === active;
        return (
          <button
            key={kind}
            ref={(el) => {
              items.current[index] = el;
            }}
            type="button"
            role="menuitem"
            tabIndex={highlighted ? 0 : -1}
            data-highlighted={highlighted ? "" : undefined}
            className={cn(MENU_ITEM, "w-full text-left")}
            onPointerEnter={() => onActiveChange(index)}
            onFocus={() => onActiveChange(index)}
            onClick={() => {
              chosen.current = true;
              onChoose(kind);
            }}
          >
            <span
              className={cn(
                "grid h-7 w-7 shrink-0 place-items-center rounded-md border transition-colors",
                highlighted ? "border-primary/40 bg-panel text-primary" : "border-transparent bg-secondary text-muted-foreground",
              )}
            >
              <Icon />
            </span>
            <span className="grid min-w-0 gap-0.5">
              <span className="truncate text-ui-xs text-foreground">{label}</span>
              {hint && <span className="truncate text-ui-2xs leading-4 text-muted-foreground">{hint}</span>}
            </span>
          </button>
        );
      })}
    </div>,
    document.body,
  );
}
