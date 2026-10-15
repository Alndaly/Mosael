import * as React from "react";

/**
 * 「点画布空白处关掉本浮层」的全局兜底。挂在 **ui 浮层这一层**(PopoverContent 调一次),
 * 所有走这套外壳的弹层(Popover / 动作菜单 MenuContent / SearchableSelect / 通知中心…)
 * 一次全修到,不再逐组件打补丁。
 *
 * ## 为什么需要它(Radix 自己的「点外部关闭」在画布上收不到)
 *
 * React Flow 的画布会把 Radix DismissableLayer 依赖的两件事都破坏掉(核实过
 * @xyflow/react 12.12.0 / d3-zoom 3.0.0 源码):
 *
 *  - **Pane 的 `onPointerDownCapture` 在选框时 `stopPropagation()`**(@xyflow/react
 *    dist/esm/index.js ~1510):冒泡到 document 的 pointerdown 被掐死在半路;
 *  - **d3-zoom 拖动画布后在 window capture 吞掉 click**(d3-zoom src/zoom.js
 *    `mousedowned` 的 `nopropagation` + mouseupped 时装的 one-time click 监听):
 *    Popover/Dialog 的 dismiss 是**延迟到 click** 的(`deferPointerDownOutside`),
 *    那个 click 永远不来。而且 mousedown 被掐断还会被 Radix 记成
 *    「interaction intercepted」,就算把 click 送过去它也不关。
 *
 * 于是挂在 body 的 radix 浮层(添加节点单子、右上角通知面板、下拉…)在画布上只能 Esc 关。
 *
 * ## 机制
 *
 * 在 **document 的 capture 阶段**监听(先于 Pane 的 capture 和 d3 的冒泡掐断),点在
 * `.react-flow__pane` **底板本身**(节点/连线/handle 是它里面的子元素,target 不会是底板)
 * 时,**另发一次 pointerdown 给 document**。这次合成的 pointerdown:
 *
 *  - target 是 document —— 不经过画布那一路 stopPropagation,Radix 挂在 document
 *    冒泡阶段的 dismiss 稳收;
 *  - `button` 用非主键 —— 走 Radix 的**非延迟分支**同步 dismiss,不等那个被吞掉的 click;
 *  - 原事件**不动**(不 stopPropagation / preventDefault)—— 拖动画布、框选、连线、
 *    节点拖动照常;合成事件 target 是 document,也不会二次触发画布里任何监听。
 *
 * 只认底板本身:点在节点/连线/浮层内容上都不触发 —— 那些地方 Radix 自己的 outside
 * 检测要么本来就收得到,要么另有语义,不由这里管。
 */
export function useDismissOnCanvasBlankPress() {
  React.useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      // 只兜底主键(左键/触控笔/单指)。右键在画布上有别的意思(画布菜单)。
      if (event.button !== 0) return;
      const target = event.target;
      // 只认画布底板:节点、连线、handle、选框、浮在画布上的面板都是它内外的别的元素,
      // target 不会是底板 —— 和 emptyCanvasDoubleClick(c canvasPointPicker)同一判据。
      if (!(target instanceof Element) || !target.classList.contains("react-flow__pane")) return;
      // MouseEvent 而不用 PointerEvent 构造:jsdom 没有 PointerEvent;Radix 只按 type 字符串
      // 和 button 分发,不校验事件的具体类型。target = document,不会回到这个监听(它只认底板)。
      document.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 1 }));
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, []);
}
