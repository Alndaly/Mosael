/**
 * 桌面版的窗口拖拽区(`-webkit-app-region`)怎么合起来:Chromium 按**文档顺序**收集(LocalFrameView::CollectDraggableRegions
 * 先序遍历布局树,和 z-index 无关),Electron 合并时重叠处**以排在后面的为准**(shell/browser/ui/drag_util.cc)。
 *
 * jsdom 没有布局,量不出谁和谁重叠,这里按最坏的算:排在 `bar` 后面、又不在它里面的 no-drag 声明,都当作盖得住它 ——
 * 弹窗的遮罩就是整窗的。返回这些元素;是空的,`bar` 自己声明的 drag 才落得下来。
 */
export function noDragAfter(bar: Element): Element[] {
  return Array.from(bar.ownerDocument.querySelectorAll("[class*='app-region:no-drag']")).filter(
    (element) => !bar.contains(element) && Boolean(bar.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING),
  );
}

/** 这个元素自己声明了 drag(拖它挪窗口)。 */
export const declaresDrag = (element: Element) => /(^|\s)\[-webkit-app-region:drag\](\s|$)/.test(element.className);
