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
