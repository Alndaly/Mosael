import React from "react";

import { clampSize, type SidebarBounds } from "@/lib/useResizableSidebar";

/**
 * 工作台右边那一列多宽(ADR 0038 §3):拖它的左边沿、在那条边上按方向键、双击回到默认宽。**唯一的来源** —— 列画多宽、
 * 原生的 ComfyUI 视图右边让出多宽,都从这里来。
 *
 * - 最窄 300(四个页签和模型列表摆得下),最宽是窗口的一半:主进程 `setShellInset` 也最多让出一半(给画布留一半)——
 *   同一条规矩,列宽和网页让出的宽永远对得上,不会一边说 700、另一边只让 600、视图压在列上。
 * - 记下的是用户拖到的宽(落盘,和别的侧栏同一个键族);窗口变窄时只是显示时夹进范围,窗口放回来就回到那个宽。
 * - 让出的宽按动画帧报给主进程(一帧最多一次),拖的时候视图边跟着走。
 *
 * **拖到原生视图上的坑**:原生视图盖在一切 DOM 上,指针一进去,渲染层就收不到 pointermove / pointerup —— 拖着拖着
 * 停住,或者松了手还在拖。所以按下时 `setPointerCapture`(指针还归这条边);收不到 pointerup 也能收住:
 * 下一个 pointermove 已经没按着键(`buttons === 0`)、pointercancel、失去捕获、窗口失焦,都当松手。
 * 此前还怕捕获不可靠,拖动期间让视图多退 96px 防指针闯进去(「DRAG_GUARD」);实测(2026-10,当前
 * Chromium)捕获已足够,保险拆了 —— 视图边完全跟手。哪天发现拖到画布上会断,git 里找回来。
 */

export const COLUMN_DEFAULT = 420;
export const COLUMN_MIN = 300;
/** 方向键一下挪多少(按住 Shift 四倍)。 */
export const COLUMN_STEP = 16;

/** 窗口这么宽时,列最宽能到多少(和主进程「最多让出一半」同一条)。 */
export const columnMax = (windowWidth: number) => Math.max(COLUMN_MIN, Math.floor(windowWidth / 2));

const STORAGE_KEY = "mosael.sidebar.v2.comfy-workbench";

function readStored(): number {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? value : COLUMN_DEFAULT;
  } catch {
    return COLUMN_DEFAULT;
  }
}

function writeStored(value: number): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // 隐私模式 / 无 storage:这次会话内照常用
  }
}

const nextFrame = (callback: () => void): (() => void) => {
  if (typeof window.requestAnimationFrame === "function") {
    const frame = window.requestAnimationFrame(callback);
    return () => window.cancelAnimationFrame(frame);
  }
  const timer = window.setTimeout(callback, 16);
  return () => window.clearTimeout(timer);
};

function useWindowWidth(): number {
  const [width, setWidth] = React.useState(() => window.innerWidth);
  React.useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

/** 让出的宽交给主进程:一帧最多报一次,报的总是最新的那个。卸载时立刻还回去(0)。 */
function useInsetReporter(inset: number): void {
  const latest = React.useRef(inset);
  const sent = React.useRef<number | null>(null);
  const cancel = React.useRef<(() => void) | null>(null);
  React.useEffect(() => {
    latest.current = inset;
    if (cancel.current) return;
    cancel.current = nextFrame(() => {
      cancel.current = null;
      if (sent.current === latest.current) return;
      sent.current = latest.current;
      void window.mosaelPageTools?.setInset(latest.current);
    });
  }, [inset]);
  React.useEffect(
    () => () => {
      cancel.current?.();
      void window.mosaelPageTools?.setInset(0);
    },
    [],
  );
}

export interface ColumnWidth {
  /** 列现在画多宽 */
  width: number;
  bounds: SidebarBounds;
  dragging: boolean;
  /** 那条可拖的边:直接摆进列里 */
  handleProps: {
    role: "separator";
    "aria-orientation": "vertical";
    "aria-valuenow": number;
    "aria-valuemin": number;
    "aria-valuemax": number;
    tabIndex: 0;
    onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
    onDoubleClick: () => void;
    onLostPointerCapture: () => void;
  };
}

export function useColumnWidth(open: boolean): ColumnWidth {
  const windowWidth = useWindowWidth();
  const bounds = React.useMemo<SidebarBounds>(
    () => ({ min: COLUMN_MIN, max: columnMax(windowWidth), fallback: COLUMN_DEFAULT }),
    [windowWidth],
  );
  const [chosen, setChosen] = React.useState(readStored);
  const [dragging, setDragging] = React.useState(false);
  const width = clampSize(bounds, chosen);
  const stopDrag = React.useRef<(() => void) | null>(null);

  const choose = React.useCallback(
    (next: number) => {
      const value = clampSize(bounds, Math.round(next));
      setChosen(value);
      writeStored(value);
    },
    [bounds],
  );

  useInsetReporter(open ? width : 0);
  React.useEffect(() => () => stopDrag.current?.(), []);

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    stopDrag.current?.();
    const handle = event.currentTarget;
    const pointer = event.pointerId;
    try {
      handle.setPointerCapture(pointer);
    } catch {
      // 拿不到捕获(测试环境、指针已经没了):靠下面那几条收住
    }
    const startX = event.clientX;
    const origin = width;
    let last = origin;
    const move = (moveEvent: PointerEvent) => {
      // 松手的那一下落在了原生视图上(渲染层没收到 pointerup):回来的第一下已经没按着键 —— 当松手
      if (moveEvent.buttons === 0) {
        finish();
        return;
      }
      // 列在右边:往左拖变宽
      last = clampSize(bounds, Math.round(origin - (moveEvent.clientX - startX)));
      setChosen(last);
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", finish);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        if (handle.hasPointerCapture?.(pointer)) handle.releasePointerCapture(pointer);
      } catch {
        // 已经放掉了
      }
      stopDrag.current = null;
      writeStored(last);
      setDragging(false);
    };
    stopDrag.current = finish;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("blur", finish);
    setDragging(true);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    const step = event.shiftKey ? COLUMN_STEP * 4 : COLUMN_STEP;
    const next =
      event.key === "ArrowLeft" ? width + step
      : event.key === "ArrowRight" ? width - step
      : event.key === "Home" ? bounds.min
      : event.key === "End" ? bounds.max
      : null;
    if (next === null) return;
    event.preventDefault();
    choose(next);
  };

  return {
    width,
    bounds,
    dragging,
    handleProps: {
      role: "separator",
      "aria-orientation": "vertical",
      "aria-valuenow": width,
      "aria-valuemin": bounds.min,
      "aria-valuemax": bounds.max,
      tabIndex: 0,
      onPointerDown,
      onKeyDown,
      onDoubleClick: () => choose(COLUMN_DEFAULT),
      onLostPointerCapture: () => stopDrag.current?.(),
    },
  };
}
