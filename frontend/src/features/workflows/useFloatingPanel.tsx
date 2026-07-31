import React from "react";

import { cn } from "@/lib/utils";

/**
 * 「可停靠 / 可悬浮」面板的几何与交互:标题栏拖动 + 八向缩放 + 位置尺寸记忆。
 *
 * 抽出来是因为工作流右侧有两个这样的面板(AI 助手、执行历史)。这套东西约一百多行,复制第二份
 * 之后它们会各自漂移 —— 一个修了越界夹取、另一个没有;一个记住了尺寸、另一个每次复位。
 *
 * 停靠态不接管任何几何:面板在网格里填满自己的格子。只有悬浮态才 fixed 定位。
 */
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
}

export function useFloatingPanel({
  storageKey,
  floating,
  minW = 320,
  minH = 380,
  preferredW = 480,
  preferredH = 640,
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

  const startDrag = (event: React.PointerEvent) => {
    if (!floating) return;
    // 标题栏里的控件不该带着窗口跑。
    if ((event.target as HTMLElement).closest("button,input,textarea,a,[role='combobox'],[data-no-drag]")) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...rect };
    const at = (cx: number, cy: number) =>
      clampRect({ ...origin, x: origin.x + (cx - startX), y: origin.y + (cy - startY) });
    const onMove = (e: PointerEvent) => setRect(at(e.clientX, e.clientY));
    const onUp = (e: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      persist(at(e.clientX, e.clientY));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
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

  /** 八个缩放手柄。停靠态返回 null。 */
  const handles = floating
    ? RESIZE_EDGES.map((edge) => (
        <div key={edge} className={cn("absolute z-[2]", HANDLE_CLASSES[edge])} onPointerDown={startResize(edge)} />
      ))
    : null;

  return {
    rect,
    /** 悬浮时的定位样式;停靠时为 undefined(交给网格)。 */
    style: floating ? ({ left: rect.x, top: rect.y, width: rect.w, height: rect.h } as const) : undefined,
    startDrag,
    handles,
  };
}
