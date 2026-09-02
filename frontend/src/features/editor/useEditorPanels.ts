import React from "react";

import { useMediaMatch } from "@/lib/useMediaMatch";
import { usePersistentTab } from "@/lib/usePersistentTab";

const PANEL_SIZES_KEY = "mosael.editor.panels.v2";

export const LEFT_TABS = ["media", "transcript", "subtitle", "voice"] as const;
export type LeftTab = (typeof LEFT_TABS)[number];

interface Bounds {
  min: number;
  max: number;
  fallback: number;
}

/** 素材是缩略图列表,窄即可;逐字稿是整篇文档,需要宽栏。宽度按页签分别记忆。 */
const LEFT_BOUNDS: Record<LeftTab, Bounds> = {
  media: { min: 180, max: 480, fallback: 252 },
  transcript: { min: 300, max: 620, fallback: 420 },
  subtitle: { min: 240, max: 520, fallback: 320 },
  voice: { min: 240, max: 520, fallback: 320 },
};
const RIGHT_BOUNDS: Bounds = { min: 200, max: 480, fallback: 264 };
const TIMELINE_BOUNDS: Bounds = { min: 160, max: 560, fallback: 252 };

/** 拖动:已经是个数,只夹范围。 */
function clamp(bounds: Bounds, value: number): number {
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

/**
 * 读盘:可能没存过、也可能存坏了,先兜底再夹。
 *
 * 和 clamp 分开是因为 fallback 只属于这一侧 —— 合成一个函数时,拖到宽度恰好为 0
 * 会走进 `|| fallback`,栏位弹回默认宽而不是收到最小值。
 */
function clampSaved(bounds: Bounds, value: unknown): number {
  return clamp(bounds, Number(value) || bounds.fallback);
}

export interface PanelSizes {
  left: Record<LeftTab, number>;
  right: number;
  timeline: number;
}

function readPanelSizes(): PanelSizes {
  let parsed: { left?: Partial<Record<LeftTab, unknown>>; right?: unknown; timeline?: unknown } = {};
  try {
    parsed = JSON.parse(window.localStorage.getItem(PANEL_SIZES_KEY) ?? "{}");
  } catch {
    // 存坏了就当没存过 —— 下面每一项都各自兜底。
  }
  const saved = parsed.left ?? {};
  return {
    left: Object.fromEntries(LEFT_TABS.map((tab) => [tab, clampSaved(LEFT_BOUNDS[tab], saved[tab])])) as Record<LeftTab, number>,
    right: clampSaved(RIGHT_BOUNDS, parsed.right),
    timeline: clampSaved(TIMELINE_BOUNDS, parsed.timeline),
  };
}

export interface EditorPanels {
  /** 当前左栏页签。切走再回来不重置 —— 见 usePersistentTab。 */
  tab: LeftTab;
  setTab: (tab: LeftTab) => void;
  /** 紧凑断点(Global rhythm):≤1000px 时编辑器收成两列,检查器改为浮动抽屉。 */
  compact: boolean;
  sizes: PanelSizes;
  /** 已按紧凑断点收过的左栏宽度,直接用于栅格。 */
  leftWidth: number;
  startDrag: (which: "left" | "right" | "timeline") => (event: React.PointerEvent) => void;
}

/**
 * 编辑器的面板摆放:哪个页签、各栏多宽、窗口够不够宽。
 *
 * 这些讲的是**这个人怎么用这个工具**,不是这一刻在剪什么 —— 所以既跟序列无关,
 * 也全都要落盘。
 */
export function useEditorPanels(): EditorPanels {
  // 在哪个 tab 是这个人的用法的一部分,不是临时值。用项目里已有的那个钩子,它自带白名单:
  // 哪天某个 tab 被删掉,存着旧值的用户不会卡在一个不存在的页面上。
  const [tab, setTab] = usePersistentTab<LeftTab>("editor-left", "media", LEFT_TABS);
  const [sizes, setSizes] = React.useState(readPanelSizes);
  const compact = useMediaMatch("(max-width: 1000px)");

  React.useEffect(() => {
    window.localStorage.setItem(PANEL_SIZES_KEY, JSON.stringify(sizes));
  }, [sizes]);

  const startDrag = (which: "left" | "right" | "timeline") => (event: React.PointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...sizes, left: { ...sizes.left } };
    const dragTab = tab;
    const onMove = (moveEvent: PointerEvent) => {
      if (which === "left") {
        const next = clamp(LEFT_BOUNDS[dragTab], origin.left[dragTab] + (moveEvent.clientX - startX));
        setSizes((current) => ({ ...current, left: { ...current.left, [dragTab]: next } }));
      } else if (which === "right") {
        const next = clamp(RIGHT_BOUNDS, origin.right - (moveEvent.clientX - startX));
        setSizes((current) => ({ ...current, right: next }));
      } else {
        const next = clamp(TIMELINE_BOUNDS, origin.timeline - (moveEvent.clientY - startY));
        setSizes((current) => ({ ...current, timeline: next }));
      }
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    // Hold the resize cursor and suppress selection for the whole drag — otherwise moving off
    // the 7px strip reverts the cursor and starts selecting whatever is underneath.
    document.body.style.cursor = which === "timeline" ? "row-resize" : "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return {
    tab,
    setTab,
    compact,
    sizes,
    leftWidth: Math.min(sizes.left[tab], compact ? 300 : Number.POSITIVE_INFINITY),
    startDrag,
  };
}
