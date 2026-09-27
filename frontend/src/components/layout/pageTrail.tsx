import React from "react";

/**
 * 顶栏左上角那条路径的**下半截**:子页面(资产详情、它的变体……)说自己在哪一层,顶栏接在页面名后面
 * 画成「资产 / 小美 / 中年」,前面几段点得回去。
 *
 * 子页面此前各自在正文里摆一颗「← 返回」,和顶栏的页面名说的是同一件事、摆了两遍;嵌套一深(变体)就是
 * 返回套返回。路径只有一条,在顶栏:页面名(点它回到这一页的起点,`onRoot`)+ 各段(`onSelect` 可点,
 * 最后一段是「你在这儿」,不可点)。
 */
export type TrailSegment = { label: string; onSelect?: () => void };
export type PageTrail = { onRoot?: () => void; segments: TrailSegment[] };

const PageTrailContext = React.createContext<(trail: PageTrail | null) => void>(() => {});

export const PageTrailProvider = PageTrailContext.Provider;

/**
 * 子页面挂载时交出自己的路径,卸载时收回。`trail` 为空 = 这一页没有下半截(列表页)。
 * 只在各段的**名字**变了时重新交一次:回调通常是就地写的箭头函数,按身份比会每次渲染都刷一遍顶栏。
 */
export function usePageTrail(trail: PageTrail | null): void {
  const publish = React.useContext(PageTrailContext);
  const latest = React.useRef(trail);
  latest.current = trail;
  const key = trail ? JSON.stringify(trail.segments.map((one) => one.label)) : "";
  React.useEffect(() => {
    const current = latest.current;
    if (!current) {
      publish(null);
      return;
    }
    //: 交出去的是一层转发:顶栏点的时候调的是**这一刻**的回调,不是交出去那一刻的。
    publish({
      onRoot: current.onRoot ? () => latest.current?.onRoot?.() : undefined,
      segments: current.segments.map((segment, index) => ({
        label: segment.label,
        onSelect: segment.onSelect ? () => latest.current?.segments[index]?.onSelect?.() : undefined,
      })),
    });
  }, [publish, key]);
  React.useEffect(() => () => publish(null), [publish]);
}
