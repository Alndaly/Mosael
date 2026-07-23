import * as React from "react";

/** 兜底修复 radix-ui/primitives#2122:从右键菜单/下拉菜单里打开对话框时,
 *  对话框挂载在菜单还没卸载完的间隙,把菜单写在 body 上的 pointer-events:none
 *  当成「原始值」记住;对话框关闭时忠实地把 none 写回 body → 整页失去响应,
 *  只能刷新。此 hook 挂在 Dialog/AlertDialog 的 Content 上:内容卸载后下一拍
 *  检查——若已无任何开着的模态层而 body 仍是 none,强制还原。 */
export function useModalPointerEventsGuard(): void {
  React.useEffect(
    () => () => {
      window.setTimeout(() => {
        const anyOpen = document.querySelector(
          '[data-state="open"]:is([role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"])',
        );
        if (!anyOpen && document.body.style.pointerEvents === "none") {
          document.body.style.pointerEvents = "";
        }
      }, 0);
    },
    [],
  );
}
