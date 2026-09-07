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
