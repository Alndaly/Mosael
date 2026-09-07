import type { OrbitControls } from "three/addons/controls/OrbitControls.js";

export type SceneNavigationMode = "trackpad" | "mouse";
export const SCENE_NAVIGATION_KEY = "mosael.scene.navigation";
export function readSceneNavigation(): SceneNavigationMode {
  try {
    return localStorage.getItem(SCENE_NAVIGATION_KEY) === "mouse"
      ? "mouse"
      : "trackpad";
  } catch {
    return "trackpad";
  }
}

/** Capture before OrbitControls: pixel scrolling is pan, not a mouse-wheel dolly. */
export function attachSceneNavigation(
  canvas: HTMLElement,
  orbit: OrbitControls,
  state: () => { mode: SceneNavigationMode; disabled: boolean },
) {
  let gestureScale: number | null = null;
  const consume = (event: Event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  const apply = (action: () => void) => {
    // Trackpads already supply momentum. Avoid integrating the same delta again as damping.
    const damping = orbit.enableDamping;
    orbit.enableDamping = false;
    try {
      action();
    } finally {
      orbit.enableDamping = damping;
    }
  };
  const zoom = (delta: number) => {
    const scale = Math.exp(-Math.min(Math.abs(delta), 100) * 0.01);
    apply(() => (delta < 0 ? orbit.dollyIn(scale) : orbit.dollyOut(scale)));
  };
  const wheel = (event: WheelEvent) => {
    const { mode, disabled } = state();
    // Even a read-only preview must not zoom the surrounding application.
    if (disabled || gestureScale !== null) {
      consume(event);
      return;
    }
    if (mode === "mouse" && !event.ctrlKey && !event.metaKey) return;
    consume(event);
    const unit =
      event.deltaMode === 1
        ? 16
        : event.deltaMode === 2
          ? canvas.clientHeight
          : 1;
    const dx = event.deltaX * unit,
      dy = event.deltaY * unit;
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    if (event.ctrlKey || event.metaKey) {
      zoom(dy);
    } else if (event.shiftKey) {
      const speed = (Math.PI * 2) / Math.max(canvas.clientHeight, 1);
      apply(() => {
        orbit.rotateLeft(dx * speed);
        orbit.rotateUp(dy * speed);
      });
    } else {
      apply(() => orbit.pan(-dx, -dy));
    }
  };
  // WebKit exposes pinching as gesture events instead of Chromium's ctrl+wheel.
  const start = (event: Event) => {
    consume(event);
    gestureScale = 1;
  };
  const change = (event: Event) => {
    consume(event);
    const scale = (event as Event & { scale: number }).scale;
    if (gestureScale === null || !Number.isFinite(scale) || scale <= 0) return;
    if (!state().disabled) zoom(-Math.log(scale / gestureScale) * 100);
    gestureScale = scale;
  };
  const end = (event: Event) => {
    consume(event);
    gestureScale = null;
  };
  canvas.addEventListener("wheel", wheel, { capture: true, passive: false });
  canvas.addEventListener("gesturestart", start, { passive: false });
  canvas.addEventListener("gesturechange", change, { passive: false });
  canvas.addEventListener("gestureend", end, { passive: false });
  return () => {
    canvas.removeEventListener("wheel", wheel, true);
    canvas.removeEventListener("gesturestart", start);
    canvas.removeEventListener("gesturechange", change);
    canvas.removeEventListener("gestureend", end);
  };
}
