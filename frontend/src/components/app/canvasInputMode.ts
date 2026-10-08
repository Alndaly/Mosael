import { useSyncExternalStore } from "react";
export type CanvasInputMode = "trackpad" | "mouse";
export const CANVAS_INPUT_KEY = "mosael.canvas.input-mode";
const changed = "mosael:canvas-input-mode";
let sessionOverride: CanvasInputMode | undefined;
export function readCanvasInputMode(): CanvasInputMode {
  if (sessionOverride) return sessionOverride;
  try {
    const value =
      localStorage.getItem(CANVAS_INPUT_KEY) ??
      localStorage.getItem("mosael.scene.navigation");
    return value === "mouse" || value === "trackpad" ? value : "trackpad";
  } catch {
    return "trackpad";
  }
}
export function setCanvasInputMode(mode: CanvasInputMode) {
  try {
    localStorage.setItem(CANVAS_INPUT_KEY, mode);
    sessionOverride = undefined;
  } catch {
    sessionOverride = mode;
  }
  window.dispatchEvent(new Event(changed));
}
function subscribe(notify: () => void) {
  const storage = (event: StorageEvent) => {
    if (
      !event.key ||
      event.key === CANVAS_INPUT_KEY ||
      event.key === "mosael.scene.navigation"
    )
      notify();
  };
  window.addEventListener(changed, notify);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(changed, notify);
    window.removeEventListener("storage", storage);
  };
}
export function useCanvasInputMode() {
  return [
    useSyncExternalStore(
      subscribe,
      readCanvasInputMode,
      () => "trackpad" as const,
    ),
    setCanvasInputMode,
  ] as const;
}

/**
 * 画布(画板、工作流)的滚轮怎么走 —— 两块画布同一份,不各写一遍。
 *
 * **不要「按住 ⌘ 滚动 = 缩放」这个键。** React Flow 缺省用 ⌘(Windows 上 Ctrl)做缩放激活键,靠 keydown / keyup
 * 记着它按没按住;可 ⌘ 的抬起常被系统吞掉(⌘+空格叫出聚焦搜索、⌘+⇧+4 截图 —— 窗口不失焦,它也就不重置),
 * 于是它一直以为 ⌘ 还按着:触控板模式下双指滑动突然变成缩放,直到下次再按一下 ⌘(用户撞上过,「有时候会变」)。
 * 缩放本来就有别的路:触控板捏合(浏览器给的是带 ctrlKey 的滚轮事件,每一次事件自己说了算,卡不住),
 * 鼠标模式下滚轮就是缩放。
 */
export function canvasWheelProps(mode: CanvasInputMode) {
  return {
    panOnScroll: mode === "trackpad",
    zoomOnScroll: mode === "mouse",
    zoomActivationKeyCode: null,
  } as const;
}

/**
 * 画布(画板、工作流)上的点击怎么算 —— 同样两块画布一份。
 *
 * **双击不缩放。** React Flow 缺省把双击交给 d3-zoom 放大一倍,而 d3-zoom 处理双击时
 * `stopImmediatePropagation`:画板上「双击空白处写一张便签」的 onDoubleClick 因此一次都没收到过,
 * 双击只是把画布放大(画板列表的空状态正教新用户这么做)。缩放有捏合、滚轮和工具条,不缺这一条。
 *
 * **⌘ / Ctrl / Shift + 点击都是「加入 / 移出选择」。** 时间线片段、3D 关键帧上三个键都是加选;React Flow
 * 缺省只认 ⌘(Windows 上 Ctrl),Shift + 点击在画布上反而是「只选这一个」。Shift + 拖空白照旧是框选。
 * 有先后顺序的列表(素材、笔记、场景列表)里 Shift 是「连选一段」,那是另一回事,见 lib/useMultiSelect。
 */
export const CANVAS_POINTER_PROPS: { zoomOnDoubleClick: boolean; multiSelectionKeyCode: string[] } = {
  zoomOnDoubleClick: false,
  multiSelectionKeyCode: ["Meta", "Control", "Shift"],
};
