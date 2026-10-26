/** The canvas backing store and the mapping from sequence coordinates into it.
 *
 * The compositor paints in sequence pixels (1920×1080, 3840×2160, …), but a
 * canvas is sampled at its CSS size × devicePixelRatio. Sizing the backing
 * store from the sequence alone leaves Retina panes upsampling the canvas —
 * a second blur on top of the proxy resolution. Keep the two spaces separate:
 * paintScene keeps its stable coordinate system, and this transform maps it
 * onto however many physical pixels the monitor actually has.
 */
export interface CanvasFrame {
  width: number;
  height: number;
}

export interface CanvasBacking {
  /** Real backing-store pixels; always at least 1×1. */
  width: number;
  height: number;
  /** sequence → backing-store scale for ctx.setTransform. */
  scaleX: number;
  scaleY: number;
}

export function canvasBackingFor(css: CanvasFrame, dpr: number, sequence: CanvasFrame): CanvasBacking {
  const width = Math.max(1, Math.round(css.width * dpr));
  const height = Math.max(1, Math.round(css.height * dpr));
  return {
    width,
    height,
    scaleX: width / Math.max(1, sequence.width),
    scaleY: height / Math.max(1, sequence.height),
  };
}
