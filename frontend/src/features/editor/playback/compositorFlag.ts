import React from "react";

/**
 * The WebCodecs canvas compositor is the STANDARD multi-track preview: one canvas composites every
 * track, so the preview equals the final picture — correct picture-in-picture, and none of the
 * per-element path's `<video>` src-reload black flash at cuts.
 *
 * The legacy per-element preview (`<video>`/`<img>`/MonitorElement in Monitor) survives ONLY as an
 * involuntary safety net — a clip whose proxy isn't ready yet, or a browser without WebCodecs —
 * never as a user-selectable "preview method". There is no UI toggle. A hidden localStorage escape
 * hatch (`openstudio.compositor = "0"`, set via devtools) can force the legacy path for debugging.
 */
const KEY = "openstudio.compositor";

export function compositorEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) !== "0"; // default ON; only an explicit "0" opts out
  } catch {
    return true;
  }
}

export function useCompositorEnabled(): boolean {
  // The escape hatch has no UI, so a single read suffices — changing it requires a reload.
  return React.useMemo(compositorEnabled, []);
}

/** WebCodecs must exist for the compositor to run; without it Monitor keeps the element fallback. */
export function compositorSupported(): boolean {
  return typeof VideoDecoder !== "undefined";
}
