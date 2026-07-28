import type { Transform } from "@/features/editor/TransformOverlay";

/**
 * The preview's canvas-drawing step: given already-resolved media + sampled transforms, paint one
 * frame. It does NOT decode, seek, sample keyframes or pick which clips are visible — callers hand
 * it a finished layer list (bottom→top).
 *
 * This paints the PREVIEW only. Export does its own compositing in ffmpeg
 * (`render_plan.py` + `render_executor.py`) and never comes through here — see
 * docs/adr/0004-preview-export-parity-by-contract.md for why the two renderers stay separate.
 * The geometry below therefore has a counterpart in the ffmpeg overlay expressions
 * (`_element_transform`): cover-fill to frame → scale → rotate → opacity → translate by
 * (x·50%, y·50%). Keep the two in step; what MUST agree literally (which layers are visible, their
 * z-order, which one is the base) is pinned by contracts/scene-cases.json.
 *
 * Text/subtitles are a separate layer either way (DOM in preview, ffmpeg CSS→PNG in export).
 */
export interface ScenePaintLayer {
  /** A decoded VideoFrame, a loaded <img>, or any other drawable source. */
  img: CanvasImageSource;
  /** Intrinsic media size (VideoFrame.displayWidth/Height or img.naturalWidth/Height). */
  mw: number;
  mh: number;
  /** Already-sampled transform at this instant (keyframes/drag resolved by the caller). */
  tf: Transform;
  /** CSS filter string (colour grade), or "" for none. May reference an in-DOM SVG curve filter. */
  filter: string;
  /** The base layer follows the sequence fill mode (cover/contain/blur); overlays always cover.
      Carried explicitly, NOT inferred from array position, so a base whose media hasn't resolved
      (dropped from the list) never lets an overlay inherit base framing. */
  isBase: boolean;
}

export interface ScenePaintOptions {
  width: number;
  height: number;
  fillMode: "cover" | "contain" | "blur";
}

type Ctx2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

/** Clear the frame and draw every layer bottom→top. Pure with respect to `layers`/`opts`; the only
    effect is on `ctx`. Identical output whether `ctx` is an on-screen canvas or an OffscreenCanvas. */
export function paintScene(ctx: Ctx2D, layers: ScenePaintLayer[], opts: ScenePaintOptions): void {
  const { width, height, fillMode } = opts;
  ctx.clearRect(0, 0, width, height);
  for (const layer of layers) {
    const { img, mw, mh, tf, filter, isBase } = layer;
    // Only the base layer follows the sequence fill mode; overlays always cover.
    // "blur" paints a full-frame blurred cover backdrop, then the sharp contain-fit picture.
    const contain = isBase && fillMode !== "cover";
    if (isBase && fillMode === "blur") {
      const bs = Math.max(width / mw, height / mh);
      ctx.save();
      ctx.filter = "blur(24px)";
      ctx.drawImage(img, (width - mw * bs) / 2, (height - mh * bs) / 2, mw * bs, mh * bs);
      ctx.restore();
    }
    const fit = contain ? Math.min(width / mw, height / mh) : Math.max(width / mw, height / mh);
    const dw = mw * fit;
    const dh = mh * fit;

    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, tf.opacity));
    ctx.filter = filter || "none";
    // Match Monitor's CSS: translate(x·50%, y·50%) of the frame, scale + rotate about center.
    ctx.translate(width / 2 + tf.x * 0.5 * width, height / 2 + tf.y * 0.5 * height);
    ctx.rotate((tf.rotation * Math.PI) / 180);
    ctx.scale(tf.scale, tf.scale);
    ctx.drawImage(img, -dw / 2, -dh / 2, dw, dh);
    ctx.restore();
  }
}
