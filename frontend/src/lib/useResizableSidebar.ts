import React from "react";

/**
 * 一条可以拖的侧栏。
 *
 * 从剪辑页那套(features/editor/useEditorPanels)提出来的 —— 那边踩过的坑这里都带着:
 * 拖动全程锁住光标和禁选(不然移出那条 7px 的窄条,光标就变回去、还开始选中底下的东西)、
 * 宽度落盘、读盘时逐项兜底。
 *
 * 剪辑页没有换成它:那边是**三条**边(左/右/时间线)且左栏按页签分别记宽度,形状不一样。
 * 硬合成一个的话,参数会比两份实现加起来还难读。
 */

export interface SidebarBounds {
  min: number;
  max: number;
  fallback: number;
}

export const DEFAULT_SIDEBAR_BOUNDS: SidebarBounds = { min: 200, max: 520, fallback: 288 };

/**
 * 拖柄长什么样 —— **全应用只有这一份**。
 *
 * 骑在 8px 列间隙正中,7px 宽的热区里一根 36px 的短竖条,常显、悬停变主色。
 * 剪辑页和对话页早就是这个样子;抽出来是因为我照着写第三份时写歪了(整条高、悬停才现、
 * 还偏了 3px),而"看起来不一样"这件事没有任何测试拦得住。
 */
export const HANDLE_PILL =
  "before:absolute before:inset-0 before:m-auto before:rounded-sm before:bg-border " +
  "before:transition-colors before:duration-100 before:content-[''] " +
  "hover:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)] " +
  "active:before:bg-[color-mix(in_srgb,var(--primary)_70%,transparent)]";

/** 竖着拖(拉宽侧栏):7px 热区里一根 36px 的短竖条。 */
export const HANDLE_COLUMN = `w-[7px] cursor-col-resize touch-none before:h-9 before:w-0.5 ${HANDLE_PILL}`;

/** 横着拖(拉高时间线):同一根条子转九十度。 */
export const HANDLE_ROW = `h-[7px] cursor-row-resize touch-none before:h-0.5 before:w-9 ${HANDLE_PILL}`;

/** 贴满整条边的竖拖柄 —— 侧栏用这个(剪辑页的三条各自内缩,自己拼 HANDLE_COLUMN)。 */
export const SIDEBAR_HANDLE_CLASS = `absolute bottom-0 top-0 z-10 ${HANDLE_COLUMN}`;

/** 热区多宽。`w-[7px]` / `h-[7px]` 说的就是它 —— 定位要减去半个热区才能居中。 */
export const HANDLE_SIZE = 7;

/**
 * 把手柄摆到**面板之间那道缝的正中**。
 *
 * `panelSize` 是前一块面板的宽/高,`gap` 是列/行间距,`padding` 是**定位上下文那个元素**
 * 自己的内边距 —— 不是页面的。手柄绝对定位在 grid 里,所以要问的是"这个 grid 有没有
 * padding":多数页面的 p-2 在外层 flex 上、grid 自己是 0(默认值),只有剪辑页是 grid
 * 自己带 p-2。默认写成 8 的话,那些页面的手柄整体偏 8px,看着就是贴在右边那块面板上。
 *
 * 收成一个函数是因为它此前是每个调用点手写的一串加法(`left + 12 + 4 - 3`),而那个 12
 * 是当年 `p-3` 的内边距 —— 后来容器改成了 `p-2`,三个调用点里的 12 一个都没跟着改,
 * 于是手柄整体偏 5px、压在右边那块面板上,看着就是"贴在一边"。**数字来自布局,不该手抄。**
 */
export function handleOffset(panelSize: number, { padding = 0, gap = 8 } = {}): number {
  return padding + panelSize + (gap - HANDLE_SIZE) / 2;
}

/** 拖动:已经是个数,只夹范围。 */
function clamp(bounds: SidebarBounds, value: number): number {
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

/** 读盘:可能没存过、也可能存坏了,先兜底再夹。合成一个函数时,拖到 0 会弹回默认宽。 */
function clampSaved(bounds: SidebarBounds, value: unknown): number {
  return clamp(bounds, Number(value) || bounds.fallback);
}

export interface ResizableSidebar {
  width: number;
  /** 按在那条窄条上开始拖。 */
  startDrag: (event: React.PointerEvent) => void;
  /** 那条可拖的窄条,直接摆进布局里。 */
  handleProps: {
    onPointerDown: (event: React.PointerEvent) => void;
    className: string;
    style: React.CSSProperties;
    role: "separator";
    "aria-orientation": "vertical";
  };
}

/**
 * @param key 落盘用的键,每个页面一个 —— 设置页和插件页各自记各自的宽度。
 */
export function useResizableSidebar(key: string, bounds: SidebarBounds = DEFAULT_SIDEBAR_BOUNDS): ResizableSidebar {
  const storageKey = `openstudio.sidebar.${key}`;
  const [width, setWidth] = React.useState(() => {
    try {
      return clampSaved(bounds, window.localStorage.getItem(storageKey));
    } catch {
      return bounds.fallback;
    }
  });

  React.useEffect(() => {
    window.localStorage.setItem(storageKey, String(width));
  }, [storageKey, width]);

  const startDrag = (event: React.PointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const origin = width;
    const onMove = (moveEvent: PointerEvent) => setWidth(clamp(bounds, origin + (moveEvent.clientX - startX)));
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    // 拖动全程锁住光标并禁选 —— 否则移出那条 7px 的窄条,光标就变回去,还开始选中底下的东西。
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return {
    width,
    startDrag,
    handleProps: {
      onPointerDown: startDrag,
      role: "separator",
      "aria-orientation": "vertical",
      className: SIDEBAR_HANDLE_CLASS,
      style: { left: handleOffset(width) },
    },
  };
}

export interface SidePanels {
  left: number;
  right: number;
  startDrag: (which: "left" | "right") => (event: React.PointerEvent) => void;
}

/**
 * 两侧都能拖的三栏布局(侧栏 / 主区 / 右栏)。
 *
 * 从对话页提出来的 —— 生成页是同一个形状却一条拖柄都没有,而照抄一份的结果只会是第三套
 * 长得不一样的实现(这一轮已经发生过一次)。
 *
 * 左右各自的上下限不同:左边是会话列表(窄一点够用),右边是参数面板(挤了填不下)。
 */
export function useSidePanels(
  key: string,
  bounds: { left: SidebarBounds; right: SidebarBounds },
): SidePanels {
  const storageKey = `openstudio.panels.${key}`;
  const [panels, setPanels] = React.useState(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? "{}");
      return { left: clampSaved(bounds.left, parsed.left), right: clampSaved(bounds.right, parsed.right) };
    } catch {
      return { left: bounds.left.fallback, right: bounds.right.fallback };
    }
  });

  React.useEffect(() => {
    window.localStorage.setItem(storageKey, JSON.stringify(panels));
  }, [storageKey, panels]);

  const startDrag = (which: "left" | "right") => (event: React.PointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const origin = { ...panels };
    const onMove = (moveEvent: PointerEvent) => {
      const dx = moveEvent.clientX - startX;
      // 右栏是**反向**的:往左拖它变宽。写成同一个方向的话,拖右边那条会觉得"反了"。
      setPanels((current) =>
        which === "left"
          ? { ...current, left: clamp(bounds.left, origin.left + dx) }
          : { ...current, right: clamp(bounds.right, origin.right - dx) },
      );
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return { left: panels.left, right: panels.right, startDrag };
}
