import { assetExportProxyUrl, assetFileUrl, type Asset, type Track } from "@/api/client";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import { clipProgress, sampleTransform } from "@/features/editor/keyframes";
import { OfflineVideoSource } from "@/features/editor/playback/OfflineVideoSource";
import { paintScene, type ScenePaintLayer } from "@/features/editor/playback/scenePaint";
import { sceneLayersAt } from "@/features/editor/playback/sceneModel";
import { readTransform } from "@/features/editor/TransformOverlay";

/**
 * The offline export renderer: `renderFrameAt(t)` composites the exact final picture at time t onto
 * an OffscreenCanvas — the export counterpart of the live preview compositor, sharing its scene
 * model ({@link sceneLayersAt}) and its draw code ({@link paintScene}). Deterministic and off the
 * rAF clock: each video source decodes its full-resolution export proxy to the exact frame and
 * awaits it, so a given t always yields the same pixels and they match the preview at that t.
 *
 * NOT YET WIRED into the export flow — the encode pipeline (P3) drives it and closes the loop; only
 * then can it be validated against the preview (pixel diff). Requires WebCodecs + the backend export
 * proxies (ensure_export_proxy) already built for every video asset used.
 *
 * Known gap (design non-goal for now): colour-curve LUTs use an in-DOM SVG feComponentTransfer that
 * an OffscreenCanvas ctx.filter url() can't resolve, so only the CSS-expressible grade is applied
 * here. Non-curve grading matches the preview exactly; curves are addressed with the encode pass.
 */
export interface OfflineRenderModel {
  tracks: Track[];
  assets: Asset[];
  width: number;
  height: number;
  fillMode: "cover" | "contain" | "blur";
}

export class OfflineFrameRenderer {
  private readonly tracks: Track[];
  private readonly assetById: Map<string, Asset>;
  private readonly width: number;
  private readonly height: number;
  private readonly fillMode: "cover" | "contain" | "blur";
  private readonly canvas: OffscreenCanvas;
  private readonly sources = new Map<string, OfflineVideoSource>(); // asset id → source
  private readonly images = new Map<string, ImageBitmap>();

  constructor(model: OfflineRenderModel) {
    this.tracks = model.tracks;
    this.assetById = new Map(model.assets.map((a) => [a.id, a]));
    this.width = model.width;
    this.height = model.height;
    this.fillMode = model.fillMode;
    this.canvas = new OffscreenCanvas(model.width, model.height);
  }

  private sourceFor(assetId: string): OfflineVideoSource {
    let source = this.sources.get(assetId);
    if (!source) {
      source = new OfflineVideoSource(assetExportProxyUrl(assetId));
      this.sources.set(assetId, source);
    }
    return source;
  }

  private async imageFor(assetId: string): Promise<ImageBitmap | null> {
    const cached = this.images.get(assetId);
    if (cached) return cached;
    try {
      const res = await fetch(assetFileUrl(assetId));
      const bitmap = await createImageBitmap(await res.blob());
      this.images.set(assetId, bitmap);
      return bitmap;
    } catch {
      return null;
    }
  }

  /** Composite the final frame at time `t` and return the OffscreenCanvas it was drawn on (reused
      across calls — the encode pass must read its pixels before the next call). */
  async renderFrameAt(t: number): Promise<OffscreenCanvas> {
    const layers = sceneLayersAt(this.tracks, this.assetById, t);
    const paint: ScenePaintLayer[] = [];
    for (const layer of layers) {
      let img: CanvasImageSource | null = null;
      let mw = 0;
      let mh = 0;
      if (layer.asset.kind === "image") {
        const bitmap = await this.imageFor(layer.asset.id);
        if (bitmap) {
          img = bitmap;
          mw = bitmap.width;
          mh = bitmap.height;
        }
      } else {
        const source = this.sourceFor(layer.asset.id);
        await source.ready.catch(() => undefined);
        const speed = layer.clip.speed || 1;
        const mediaSec = layer.clip.src_in + (t - layer.clip.timeline_start) * speed;
        const frame = await source.frameAt(mediaSec);
        if (frame) {
          img = frame;
          mw = frame.displayWidth;
          mh = frame.displayHeight;
        }
      }
      if (!img) continue; // a source that failed to build/decode is simply absent (as in preview)
      const tf = sampleTransform(readTransform(layer.clip.transform), clipProgress(layer.clip, t));
      const filter = computeFilters((layer.clip.effects ?? {}) as ClipEffects).cssFilter;
      paint.push({ img, mw, mh, tf, filter, isBase: layer.isBase });
    }
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("OffscreenCanvas 2D context unavailable");
    // VideoFrames belong to their source's GOP cache (reused across adjacent t) — draw, don't close.
    paintScene(ctx, paint, { width: this.width, height: this.height, fillMode: this.fillMode });
    return this.canvas;
  }

  close(): void {
    for (const source of this.sources.values()) source.close();
    this.sources.clear();
    for (const bitmap of this.images.values()) bitmap.close();
    this.images.clear();
  }
}
