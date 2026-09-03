import type { Transform } from "@/features/editor/TransformOverlay";
import type { ClipAppearance, MaskShape } from "@/features/editor/clipAppearance";

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
  /** Geometry and drop shadow, resolved from clip.effects.appearance. */
  appearance: ClipAppearance;
}

export interface ScenePaintOptions {
  width: number;
  height: number;
  fillMode: "cover" | "contain" | "blur";
}

type Ctx2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

function maskPath(ctx: Ctx2D, shape: MaskShape, x: number, y: number, width: number, height: number, radius: number): void {
  ctx.beginPath();
  if (shape === "circle") {
    ctx.arc(0, 0, width / 2, 0, Math.PI * 2);
  } else if (shape === "rounded") {
    ctx.roundRect(x, y, width, height, Math.min(width, height) * radius);
  } else {
    ctx.rect(x, y, width, height);
  }
}

function shadowColor(color: string, opacity: number): string {
  const r = Number.parseInt(color.slice(1, 3), 16);
  const g = Number.parseInt(color.slice(3, 5), 16);
  const b = Number.parseInt(color.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

/** Clear the frame and draw every layer bottom→top. Pure with respect to `layers`/`opts`; the only
    effect is on `ctx`. Identical output whether `ctx` is an on-screen canvas or an OffscreenCanvas. */
export function paintScene(ctx: Ctx2D, layers: ScenePaintLayer[], opts: ScenePaintOptions): void {
  const { width, height, fillMode } = opts;
  ctx.clearRect(0, 0, width, height);
  for (const layer of layers) {
    const { img, mw, mh, tf, filter, isBase, appearance } = layer;
    // Only an unstyled base layer follows the sequence fill mode. Once it has a mask/shadow it is
    // a free visual element over black (the export path makes the same transition); otherwise a
    // blurred/contained base would leak a full-frame backdrop behind a supposedly circular clip.
    // "blur" paints a full-frame blurred cover backdrop, then the sharp contain-fit picture.
    const freeElement = appearance.mask.shape !== "none" || appearance.shadow.enabled;
    const followsBaseFill = isBase && !freeElement;
    const contain = followsBaseFill && fillMode !== "cover";
    if (followsBaseFill && fillMode === "blur") {
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
    const circle = appearance.mask.shape === "circle";
    const drawWidth = circle ? Math.min(dw, dh) : dw;
    const drawHeight = circle ? drawWidth : dh;
    const drawX = -drawWidth / 2;
    const drawY = -drawHeight / 2;

    // Paint the silhouette first so its shadow is not clipped by the mask. The media draw below
    // completely covers this fill; only the blurred/offset pixels remain visible around it.
    if (appearance.shadow.enabled && appearance.shadow.opacity > 0) {
      ctx.filter = "none";
      ctx.fillStyle = appearance.shadow.color;
      ctx.shadowColor = shadowColor(appearance.shadow.color, appearance.shadow.opacity);
      ctx.shadowBlur = appearance.shadow.blur;
      ctx.shadowOffsetX = appearance.shadow.offsetX;
      ctx.shadowOffsetY = appearance.shadow.offsetY;
      maskPath(ctx, appearance.mask.shape, drawX, drawY, drawWidth, drawHeight, appearance.mask.radius);
      ctx.fill();
      ctx.shadowColor = "rgba(0, 0, 0, 0)";
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;
    }

    if (appearance.mask.shape !== "none") {
      maskPath(ctx, appearance.mask.shape, drawX, drawY, drawWidth, drawHeight, appearance.mask.radius);
      ctx.clip();
    }
    ctx.filter = filter || "none";
    if (circle) {
      // Preserve source proportions: crop its central square, then map square→circle. Drawing the
      // whole 16:9 source into a square would make faces visibly narrow.
      const sourceSide = Math.min(mw, mh);
      ctx.drawImage(
        img,
        (mw - sourceSide) / 2,
        (mh - sourceSide) / 2,
        sourceSide,
        sourceSide,
        drawX,
        drawY,
        drawWidth,
        drawHeight,
      );
    } else {
      ctx.drawImage(img, drawX, drawY, drawWidth, drawHeight);
    }
    ctx.restore();
  }
}
