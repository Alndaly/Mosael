import React from "react";
import { createPortal } from "react-dom";

import { HintRegion } from "@/components/ui/tooltip";

/**
 * 原生视图(内嵌浏览器、ComfyUI 工作台)在前台时,**外壳顶栏**上留的一个位(ADR 0051)。
 *
 * 后台冒出来的、常驻的浮层 —— 等人拍板的确认卡、免提浮标 —— 平时浮在页面上;原生视图一亮,页面整块在网页底下,它们也就
 * 看不见了。自己跳出来盖住正在看的网页也不合适(人正在登录、正在看画布),所以收成外壳顶栏上的一个小标:确认卡是
 * 「N 张卡等你拍板」,点了才让开、展开;免提浮标是一个图标,说话照常。视图收起,它们回到原来的地方。
 *
 * 内嵌浏览器的顶栏(App 的 PublishViewBar)和工作台的顶栏(ComfyWorkbench)各挂一个 `<ChromeStatusSlot>`,同一时刻只亮一条;
 * 要住进来的组件用 `useChromeStatusSlot()` 拿到它,经 `<InChromeStatusSlot>` 放进去。顶栏里的控件按那一条的尺寸来
 * (内嵌浏览器 xs、工作台 sm)。
 */
export type ChromeStatusSlotSize = "xs" | "sm";

export interface ChromeStatusSlotTarget {
  element: HTMLElement;
  size: ChromeStatusSlotSize;
}

let current: ChromeStatusSlotTarget | null = null;
const listeners = new Set<() => void>();

function publish(next: ChromeStatusSlotTarget | null): void {
  if (next?.element === current?.element && next?.size === current?.size) return;
  current = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 外壳顶栏上的那个位;没有亮着的顶栏时是 null(原生视图不在前台)。 */
export function useChromeStatusSlot(): ChromeStatusSlotTarget | null {
  return React.useSyncExternalStore(subscribe, () => current, () => null);
}

/** 挂在外壳顶栏里。空着的时候不占地方。 */
export function ChromeStatusSlot({ size }: { size: ChromeStatusSlotSize }) {
  const ref = React.useCallback(
    (element: HTMLDivElement | null) => {
      if (!element) return;
      publish({ element, size });
      // 卸下(顶栏收起、换成另一条)时撤掉 —— 已经换成别人的了就不动
      return () => {
        if (current?.element === element) publish(null);
      };
    },
    [size],
  );
  return (
    <div
      ref={ref}
      data-chrome-status-slot=""
      className="flex shrink-0 items-center gap-1.5 empty:hidden [-webkit-app-region:no-drag]"
    />
  );
}

/** 顶栏里的说明往下出,交给浮层视图画在网页上面(同顶栏自己的那些,见 HintRegion)。 */
const SLOT_REGION = { side: "bottom" as const };

/**
 * 把内容放进外壳顶栏的那个位。portal 过去的内容拿不到顶栏的 React 上下文,所以在这里补上顶栏的说明范围:不补,悬停说明
 * 照常画在 DOM 里 —— 在网页底下,看不见。
 */
export function InChromeStatusSlot({ slot, children }: { slot: ChromeStatusSlotTarget; children: React.ReactNode }) {
  return createPortal(<HintRegion.Provider value={SLOT_REGION}>{children}</HintRegion.Provider>, slot.element);
}
