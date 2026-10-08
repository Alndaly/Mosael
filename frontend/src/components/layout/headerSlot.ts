import React from "react";

/**
 * 应用顶栏右侧那一簇里留的一个位(AppShell 画它)。浮在页面上的东西**收起来以后**住这里:顶栏是应用自己的,
 * 不盖任何一页的工具条 —— 收起来的东西还浮在页面右上角的话,盖住的正是各页工具条最右边那几颗按钮(笔记页的
 * 「AI 助手」、AI Studio 的「智能体环境」),收了等于没收。
 */
export const HEADER_STATUS_SLOT_ID = "app-header-status";

/** 顶栏里那个位;没有顶栏(单独渲染、测试)时是 null,调用方自己找个地方放。 */
export function useHeaderStatusSlot(): HTMLElement | null {
  const [slot, setSlot] = React.useState<HTMLElement | null>(null);
  React.useEffect(() => setSlot(document.getElementById(HEADER_STATUS_SLOT_ID)), []);
  return slot;
}
