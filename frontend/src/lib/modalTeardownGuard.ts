import * as React from "react";

/** 一个模态层为了「锁住外面」而写在 <body> 上的全局副作用。关闭时应当全部撤销。 */
const BODY_SIDE_EFFECTS = ["pointer-events", "overflow"] as const;

const OPEN_MODAL_SELECTOR =
  '[data-state="open"]:is([role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"])';

/** 只用到这几个成员;抽成接口是为了能在没有 DOM 环境的测试里传替身(仓库里没装 jsdom)。 */
export interface ModalTeardownTarget {
  querySelector(selector: string): unknown;
  body: {
    style: Pick<CSSStyleDeclaration, "getPropertyValue" | "removeProperty">;
    removeAttribute(name: string): void;
  };
}

/**
 * 撤销 <body> 上残留的模态副作用。已无任何打开的模态层时才动手。
 *
 * Radix 的模态层会在 body 上留下两类痕迹,正常路径下由它自己回收:
 *  1. `pointer-events: none` —— 屏蔽层外交互;
 *  2. `overflow: hidden` + `data-scroll-locked`(react-remove-scroll)—— 锁住背景滚动,
 *     同时挂一个**非 passive 的 wheel 监听**,拦掉自己 shard 之外的一切滚轮。
 *
 * 两者都有卡住不还原的已知路径:
 *  - `pointer-events`:从右键/下拉菜单里打开对话框时,菜单还没卸载完,对话框把菜单写的 none 当成
 *    「原始值」记住,关闭时忠实写回 → 整页失去响应(radix-ui/primitives#2122)。
 *  - 滚动锁:它的释放挂在 overlay **退场动画结束**之后(Radix 用 Presence 等 animationend)。
 *    动画走不完就永远不卸载 —— 而 Chromium 在页面隐藏/窗口被遮挡时会**暂停动画**(实测:隐藏时
 *    overlay 动画 currentTime 恒为 0、playState 仍是 running,1.2 秒后 body 仍留着 overflow:hidden
 *    与 data-scroll-locked)。这个应用是 Electron 桌面端,关对话框那一瞬切走窗口太常见了。
 *    一旦卡住,不只整页不能滚,portal 到 body 的浮层(下拉列表等)也会被那个 wheel 监听继续拦住 ——
 *    「下拉列表突然滚不动了」就是这么来的。
 *
 */
export function releaseStaleModalSideEffects(target: ModalTeardownTarget = document): void {
  // 还有模态层开着就什么都不做 —— 那些副作用此刻是正当的。
  if (target.querySelector(OPEN_MODAL_SELECTOR)) return;
  for (const property of BODY_SIDE_EFFECTS) {
    if (target.body.style.getPropertyValue(property)) {
      target.body.style.removeProperty(property);
    }
  }
  // react-remove-scroll 的标记:留着会让后续判断以为仍在锁定状态。
  target.body.removeAttribute("data-scroll-locked");
}

/** 挂在 Dialog / AlertDialog 的 Content 上:内容卸载后下一拍复查并兜底清理。
 *  逻辑本体放在上面的纯函数里,便于直接单测(不必挂载组件)。 */
export function useModalTeardownGuard(): void {
  React.useEffect(() => () => void window.setTimeout(releaseStaleModalSideEffects, 0), []);
}
