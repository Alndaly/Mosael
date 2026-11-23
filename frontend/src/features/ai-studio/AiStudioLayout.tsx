import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { SIDEBAR_HANDLE_CLASS, handleOffset, useSidePanels } from "@/lib/useResizableSidebar";

//: 分栏宽度的边界。上限挡的是"把中间对话挤没了",下限挡的是"栏窄到内容全在换行"。
export const AI_PANEL_BOUNDS = {
  left: { min: 180, max: 340, fallback: 240 },
  right: { min: 240, max: 460, fallback: 300 },
} as const;

//: 窄到这一档只剩中间那一栏(左栏收进 StudioIndex 的浮窗,右栏由页面自己决定怎么放)。
const SINGLE_COLUMN = "(max-width: 820px)";

/**
 * AI Studio 两张页(对话、创作)的外壳:左栏会话列表 | 中间 | 右栏,两条拖柄压在分割线上,宽度按 `panelKey` 各记各的。
 *
 * 此前两页各写一份:同一段「几栏都开 / 只开左 / 只开右」的 gridTemplateColumns 三元链、同两条拖柄、同一个 820px 断点。
 * 内联 gridTemplateColumns 会盖掉 class 里的 `max-[…]` 回退,所以断点在 JS 里判 —— 单列也显式写,
 * 避免 matchMedia 的 ≤ 与 CSS max-width 的 < 在断点处不一致。
 *
 * 子元素按顺序就是各栏:左栏(通常是 `<StudioIndex>`,`left` 为假时不渲染)、中间、右栏(`right` 为假时不渲染)。
 */
export function AiStudioLayout({
  panelKey,
  left,
  right,
  className,
  children,
}: {
  /** 栏宽落盘用的键:两页各记各的。 */
  panelKey: string;
  /** 页面想开左栏(会话列表)。窄屏下仍由布局收成单列。 */
  left: boolean;
  /** 页面想开右栏,且已按自己的窄屏规矩判过(右栏窄屏下怎么放各页不同)。 */
  right: boolean;
  /** 页面额外的行规矩(例如对话页窄屏下输入框另起一行)。 */
  className?: string;
  children: ReactNode;
}) {
  const panels = useSidePanels(panelKey, AI_PANEL_BOUNDS);
  const single = useMediaMatch(SINGLE_COLUMN);
  const showLeft = left && !single;
  const columns = single
    ? "minmax(0,1fr)"
    : [showLeft && `${panels.left}px`, "minmax(0,1fr)", right && `${panels.right}px`].filter(Boolean).join(" ");
  return (
    <div className={cn("relative grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)]", className)} style={{ gridTemplateColumns: columns }}>
      {/* 拖柄压在栏与栏之间那条分割线上 —— 和剪辑页同款。 */}
      {showLeft && (
        <div className={SIDEBAR_HANDLE_CLASS} style={{ left: handleOffset(panels.left) }} onPointerDown={panels.startDrag("left")} />
      )}
      {right && (
        <div className={SIDEBAR_HANDLE_CLASS} style={{ right: handleOffset(panels.right) }} onPointerDown={panels.startDrag("right")} />
      )}
      {children}
    </div>
  );
}
