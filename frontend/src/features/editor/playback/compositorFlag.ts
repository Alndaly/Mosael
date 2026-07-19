import React from "react";

/**
 * Opt-in switch for the WebCodecs canvas compositor (per-device, localStorage).
 * Off by default during rollout; the element-based preview stays the fallback.
 */
const KEY = "mibu.compositor";
const EVENT = "mibu:compositor";

export function compositorEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setCompositorEnabled(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
    window.dispatchEvent(new Event(EVENT));
  } catch {
    /* storage unavailable — ignore */
  }
}

export function useCompositorEnabled(): boolean {
  const [on, setOn] = React.useState(compositorEnabled);
  React.useEffect(() => {
    const handler = () => setOn(compositorEnabled());
    window.addEventListener(EVENT, handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener(EVENT, handler);
      window.removeEventListener("storage", handler);
    };
  }, []);
  return on;
}

/** WebCodecs must exist for the compositor to run at all. */
export function compositorSupported(): boolean {
  return typeof VideoDecoder !== "undefined";
}
