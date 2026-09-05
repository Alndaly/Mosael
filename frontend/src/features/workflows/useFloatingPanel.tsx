import React from "react";

import { cn } from "@/lib/utils";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";

/**
 * 「可停靠 / 可悬浮」面板的几何与交互:标题栏拖动 + 八向缩放 + 位置尺寸记忆。
 *
 * 抽出来是因为工作流右侧有两个这样的面板(AI 助手、执行历史)。这套东西约一百多行,复制第二份
 * 之后它们会各自漂移 —— 一个修了越界夹取、另一个没有;一个记住了尺寸、另一个每次复位。
 *
 * 停靠态不接管任何几何:面板在网格里填满自己的格子。只有悬浮态才 fixed 定位。
 */
/** 两个面板共用的标题栏刻度:同样的高度、内边距、按钮间距。
 *  各写各的时候,并排放在右栏里按钮疏密一眼就能看出不一样。 */
export const PANEL_HEADER_CLASS =
  "flex h-[34px] cursor-default select-none touch-none items-center gap-1 border-b border-border pl-2.5 pr-1.5 [&_h2]:m-0 [&_h2]:flex [&_h2]:flex-1 [&_h2]:items-center [&_h2]:gap-1.5 [&_h2]:text-ui-sm [&_h2]:font-semibold";

/** 停靠和悬浮面板共用的外框。智能体与执行历史必须是一套圆角和边界。 */
export const DOCKABLE_PANEL_FRAME_CLASS =
  `overflow-hidden rounded-lg ${CANVAS_GLASS_SURFACE_CLASS}`;

/**
 * 悬浮窗的叠放次序:一个从底到顶的 id 序列,z-index = BASE + 下标。
 *
 * 之前两个面板都写死 z-[55],谁在上完全由 DOM 顺序决定,用户没有任何手段调整 —— 两个都浮着
 * 又叠在一起时,下面那个就是够不着。
 *
 * **下限是 BASE 而不是 0**:降级只在悬浮窗之间重排,永远不会掉到页面内容底下。否则"降到最低"
 * 会把窗口压到画布之下,变成一个既看不见也点不到、只能靠清 localStorage 找回来的状态。
 *
 * 放模块级而不是 context:这个 hook 的两个使用者分别在各自的组件树里,套一层 Provider 只是
 * 为了让它们看见同一个数组,不值得。
 */
const Z_BASE = 55;

let zOrder: string[] = [];
let focusedId: string | null = null;
const zListeners = new Set<() => void>();
const emitZ = () => {
  for (const listener of zListeners) listener();
};
const subscribeZ = (listener: () => void) => {
  zListeners.add(listener);
  return () => {
    zListeners.delete(listener);
  };
};
/** 快照必须保持引用稳定,否则 useSyncExternalStore 会判定每次都变、无限重渲染。 */
const getZOrder = () => zOrder;

/** 当前有没有悬浮窗握着"层级快捷键"。
 *
 * 画布上的节点用同一组 Cmd/Ctrl+[ ] 调层级,两边都监听同一个键,必须有一处仲裁 ——
 * 否则按一次会既动窗口又动节点。规则是"最后碰过谁就归谁":点了悬浮窗归窗口,
 * 点回画布归画布(画布那边显式调 blurFloatingPanels)。 */
export const hasFocusedFloatingPanel = () => focusedId !== null;

/** 把焦点交还给调用方(画布)。点画布就该轮到节点响应快捷键。 */
export function blurFloatingPanels() {
  focusedId = null;
}

function raiseToTop(id: string) {
  focusedId = id;
  if (zOrder[zOrder.length - 1] === id) return;
  zOrder = [...zOrder.filter((item) => item !== id), id];
  emitZ();
}

function sendToBottom(id: string) {
  if (zOrder[0] === id) return;
  zOrder = [id, ...zOrder.filter((item) => item !== id)];
  emitZ();
}

export interface FloatRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 八向缩放:每个手柄声明它拉动哪几条边。 */
const RESIZE_EDGES = ["n", "s", "e", "w", "ne", "nw", "se", "sw"] as const;
type ResizeEdge = (typeof RESIZE_EDGES)[number];

/* 6px 隐形命中区骑在边框上;右下角给两道弧线的可见暗示。 */
const HANDLE_CLASSES: Record<ResizeEdge, string> = {
  n: "left-2.5 right-2.5 top-[-3px] h-1.5 cursor-ns-resize",
  s: "bottom-[-3px] left-2.5 right-2.5 h-1.5 cursor-ns-resize",
  e: "bottom-2.5 right-[-3px] top-2.5 w-1.5 cursor-ew-resize",
  w: "bottom-2.5 left-[-3px] top-2.5 w-1.5 cursor-ew-resize",
  ne: "right-[-3px] top-[-3px] h-3 w-3 cursor-nesw-resize",
  sw: "bottom-[-3px] left-[-3px] h-3 w-3 cursor-nesw-resize",
  nw: "left-[-3px] top-[-3px] h-3 w-3 cursor-nwse-resize",
  se: "bottom-[-3px] right-[-3px] h-3 w-3 cursor-nwse-resize after:absolute after:bottom-1 after:right-1 after:h-[7px] after:w-[7px] after:rounded-br-[3px] after:border-b-2 after:border-r-2 after:border-border-strong after:opacity-70 after:content-['']",
};

export interface FloatingPanelOptions {
  /** localStorage 键。两个面板各记各的位置。 */
  storageKey: string;
  /** 是否处于悬浮态。停靠时所有交互都不接管。 */
  floating: boolean;
  minW?: number;
  minH?: number;
  /** 悬浮时的初始大小(会按视口夹取)。 */
  preferredW?: number;
  preferredH?: number;
  /**
   * 整个面板都是拖动把手,不只是标题栏。
   *
   * 面板有标题栏可拖,所以默认排除按钮、输入框这些控件 —— 在文本框里选一段字不该
   * 把窗口甩走。**但语音浮标整个就是一颗按钮**:那条排除规则把它的全部表面都算成了
   * "控件",于是它一步也拖不动。开了这个之后只剩 `[data-no-drag]` 一道排除,
   * 需要保持可点的东西自己标出来。
   */
  dragAnywhere?: boolean;
}

export function useFloatingPanel({
  storageKey,
  floating,
  minW = 320,
  minH = 380,
  preferredW = 480,
  preferredH = 640,
  dragAnywhere = false,
}: FloatingPanelOptions) {
  const clampRect = React.useCallback(
    (rect: FloatRect): FloatRect => {
      const w = Math.min(Math.max(rect.w, minW), window.innerWidth - 24);
      const h = Math.min(Math.max(rect.h, minH), window.innerHeight - 24);
      return {
        w,
        h,
        x: Math.min(Math.max(rect.x, 8), window.innerWidth - w - 8),
        // 底部留一截:整窗被拖出屏幕外就再也抓不回来了。
        y: Math.min(Math.max(rect.y, 8), window.innerHeight - 60),
      };
    },
    [minW, minH],
  );

  const [rect, setRect] = React.useState<FloatRect>(() => {
    // 随视口取,小屏不顶满、大屏不寒酸;落位右下角。
    const w = Math.min(preferredW, window.innerWidth - 48);
    const h = Math.min(preferredH, window.innerHeight - 96);
    const fallback = { x: window.innerWidth - w - 20, y: window.innerHeight - h - 44, w, h };
    try {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? "");
      return clampRect({ x: Number(parsed.x), y: Number(parsed.y), w: Number(parsed.w), h: Number(parsed.h) });
    } catch {
      return clampRect(fallback);
    }
  });

  const persist = React.useCallback(
    (next: FloatRect) => window.localStorage.setItem(storageKey, JSON.stringify(next)),
    [storageKey],
  );

  /** 这一次按下之后指针挪了多远。**给"整个面板都能拖"的调用方分辨拖和点用** ——
   *  同一颗按钮既要拖得走又要点得开,而"拖完手一松顺带触发了一次点击"是最气人的一种。 */
  const movedRef = React.useRef(0);

  const startDrag = (event: React.PointerEvent) => {
    if (!floating) return;
    // 标题栏里的控件不该带着窗口跑。整体拖动时只认显式标记的那些。
    const exclude = dragAnywhere ? "[data-no-drag]" : "button,input,textarea,a,[role='combobox'],[data-no-drag]";
    if ((event.target as HTMLElement).closest(exclude)) return;
    event.preventDefault();
    movedRef.current = 0;
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...rect };
    const at = (cx: number, cy: number) =>
      clampRect({ ...origin, x: origin.x + (cx - startX), y: origin.y + (cy - startY) });
    const onMove = (e: PointerEvent) => {
      movedRef.current = Math.max(movedRef.current, Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY));
      setRect(at(e.clientX, e.clientY));
    };
    const onUp = (e: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      persist(at(e.clientX, e.clientY));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  /** 刚才那一下是拖动,不是点击。阈值 4px:手不稳带来的一两像素不该吃掉一次点击。
   *
   *  **读一次就清零**,所以它只对紧接着的那一次点击有效。不清的话,键盘敲回车触发的
   *  click 会读到上一次拖动留下的位移 —— 拖过一次之后这颗按钮就再也按不动了,
   *  而这种失效只有用键盘的人碰得到。 */
  const wasDragged = () => {
    const dragged = movedRef.current > 4;
    movedRef.current = 0;
    return dragged;
  };

  // 拖 n/w 边时同步移动 x/y(锚定对边)。用自定义手柄而不是原生 resize:后者只有右下一个
  // 不显眼的小角,且在 fixed + 手动定位下无法向上/向左扩展。
  const startResize = (edge: ResizeEdge) => (event: React.PointerEvent) => {
    if (!floating) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...rect };
    const apply = (clientX: number, clientY: number): FloatRect => {
      const dx = clientX - startX;
      const dy = clientY - startY;
      let { x, y, w, h } = origin;
      if (edge.includes("e")) w = origin.w + dx;
      if (edge.includes("s")) h = origin.h + dy;
      if (edge.includes("w")) {
        w = Math.min(Math.max(origin.w - dx, minW), origin.x + origin.w - 8);
        x = origin.x + origin.w - w;
      }
      if (edge.includes("n")) {
        h = Math.min(Math.max(origin.h - dy, minH), origin.y + origin.h - 8);
        y = origin.y + origin.h - h;
      }
      return clampRect({ x, y, w, h });
    };
    const onMove = (e: PointerEvent) => setRect(apply(e.clientX, e.clientY));
    const onUp = (e: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      persist(apply(e.clientX, e.clientY));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  /* ── 叠放次序 ────────────────────────────────────────────────────────────── */

  const order = React.useSyncExternalStore(subscribeZ, getZOrder, getZOrder);

  React.useEffect(() => {
    if (!floating) return;
    // 新浮起来的窗口置顶并接管焦点 —— 刚打开就被压在别的窗口下面是说不通的。
    raiseToTop(storageKey);
    return () => {
      zOrder = zOrder.filter((item) => item !== storageKey);
      if (focusedId === storageKey) focusedId = zOrder[zOrder.length - 1] ?? null;
      emitZ();
    };
  }, [floating, storageKey]);

  React.useEffect(() => {
    if (!floating) return;
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      if (event.key !== "[" && event.key !== "]") return;
      // 每个悬浮窗都装了这个监听,只有拿到焦点的那个真正动作。
      if (focusedId !== storageKey) return;
      // 必须拦掉:Chromium 里 Cmd/Ctrl+[ 和 ] 是后退/前进,不拦会把整个应用导航走。
      event.preventDefault();
      if (event.key === "]") raiseToTop(storageKey);
      else sendToBottom(storageKey);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [floating, storageKey]);

  /** 摊到面板根节点上:点哪儿都能让这个窗口拿到焦点并置顶。
   *
   *  **捕获阶段是必需的**:标题栏拖动和八向缩放的 pointerdown 都会 stopPropagation,
   *  冒泡阶段的监听在那两处收不到事件 —— 于是"拖一下窗口"反而不能把它带到最前,
   *  而拖动恰恰是最常伴随置顶意图的操作。 */
  const focusProps = floating ? { onPointerDownCapture: () => raiseToTop(storageKey) } : {};

  /** 八个缩放手柄。停靠态返回 null。 */
  const handles = floating
    ? RESIZE_EDGES.map((edge) => (
        <div key={edge} className={cn("absolute z-[2]", HANDLE_CLASSES[edge])} onPointerDown={startResize(edge)} />
      ))
    : null;

  return {
    rect,
    /** 悬浮时的定位样式与层级;停靠时为 undefined(交给网格)。 */
    style: floating
      ? ({
          left: rect.x,
          top: rect.y,
          width: rect.w,
          height: rect.h,
          zIndex: Z_BASE + Math.max(order.indexOf(storageKey), 0),
        } as const)
      : undefined,
    startDrag,
    wasDragged,
    handles,
    focusProps,
  };
}
