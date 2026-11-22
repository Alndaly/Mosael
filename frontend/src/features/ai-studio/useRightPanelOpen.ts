import React from "react";

/**
 * AI Studio 右栏(对话的「智能体环境」、生成的「引擎参数」)的开合。
 *
 * 宽屏它是停靠的一栏,默认开;窄屏(`narrow`)它变成浮在内容上的抽屉,**默认关** ——
 * 抽屉一进页面就开着,会盖住标题、推荐和输入框(1024 宽实测输入框被压掉一半)。
 *
 * 两种宽度各记各的:窄屏里开关抽屉不改宽屏的停靠状态;窗口拉回宽屏时抽屉随之收起,
 * 再变窄也不会自己弹出来。
 */
export function useRightPanelOpen(narrow: boolean): readonly [boolean, (open: boolean) => void] {
  const [docked, setDocked] = React.useState(true);
  const [drawer, setDrawer] = React.useState(false);
  React.useEffect(() => {
    if (!narrow) setDrawer(false);
  }, [narrow]);
  const setOpen = React.useCallback((open: boolean) => (narrow ? setDrawer : setDocked)(open), [narrow]);
  return [narrow ? drawer : docked, setOpen] as const;
}
