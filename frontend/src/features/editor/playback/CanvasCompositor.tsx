import React from "react";

import { assetFileUrl, assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { CURVES_FILTER_ID } from "@/features/editor/colorCurves";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import { ProxyVideoSource } from "@/features/editor/playback/ProxyVideoSource";
import { evictions } from "@/features/editor/playback/sourcePool";
import { readTransform, type Transform } from "@/features/editor/TransformOverlay";
import { clipProgress, sampleTransform } from "@/features/editor/keyframes";
import { useEditorStore } from "@/stores/editorStore";

export interface CompositorLayer {
  clip: Clip;
  asset: Asset;
  /** Live transform while dragging the on-canvas handles. */
  transformOverride?: Transform | null;
}

/**
 * S2 of the compositor: every active video/image clip drawn onto ONE canvas in z-order
 * (bottom → top), each with its own transform, opacity and colour grade — replacing the
 * base `<video>` plus N overlay elements with a single decode-and-composite pass. Video
 * clips decode from their proxy via {@link ProxyVideoSource}; images blit from a cached
 * `<img>`. The rAF loop reads layers + playhead from refs so paint never restarts on a
 * React re-render.
 */
export function CanvasCompositor({
  layers,
  width,
  height,
  fillMode = "cover",
  className,
  style,
  onSourceFailed,
  scopeCanvasRef,
}: {
  layers: CompositorLayer[];
  width: number;
  height: number;
  /** Base-layer fit, matching the sequence reframe (overlay layers always cover). */
  fillMode?: "cover" | "contain" | "blur";
  className?: string;
  style?: React.CSSProperties;
  /** A proxy that cannot be decoded here. The caller should drop back to element playback —
      otherwise the layer simply never paints and the viewer sees an unexplained black frame. */
  onSourceFailed?: (assetId: string) => void;
  /** Mirror the composited canvas out to the caller (scopes read the final graded frame from it;
      images are drawn crossOrigin so it stays getImageData-readable). */
  scopeCanvasRef?: React.MutableRefObject<HTMLCanvasElement | null>;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const sourcesRef = React.useRef<Map<string, ProxyVideoSource>>(new Map());
  // Sources whose clip is no longer under the playhead. Closing them immediately meant that
  // scrubbing back across a cut re-fetched and re-parsed the whole proxy; keeping a few alive
  // makes crossing a boundary free in both directions. Bounded by retained bytes, not count,
  // because one long proxy costs far more than several short ones.
  const idleRef = React.useRef<Map<string, ProxyVideoSource>>(new Map());
  const onSourceFailedRef = React.useRef(onSourceFailed);
  onSourceFailedRef.current = onSourceFailed;
  const reportedFailures = React.useRef<Set<string>>(new Set());
  // Set whenever anything that affects the picture changes; the draw loop clears it once the
  // frame it produced has settled.
  const dirtyRef = React.useRef(true);
  const imagesRef = React.useRef<Map<string, HTMLImageElement>>(new Map());
  const layersRef = React.useRef(layers);
  layersRef.current = layers;
  const fillModeRef = React.useRef(fillMode);
  fillModeRef.current = fillMode;
  React.useEffect(() => {
    dirtyRef.current = true;
  }, [width, height, fillMode]);

  // Per-clip filter strings; curve LUTs need an SVG feComponentTransfer rendered in the DOM.
  const filters = React.useMemo(
    () =>
      layers.map((layer) => {
        const info = computeFilters((layer.clip.effects ?? {}) as ClipEffects);
        const id = `${CURVES_FILTER_ID}-cmp-${layer.clip.id}`;
        const filter = [info.cssFilter, info.curveTables ? `url(#${id})` : ""].filter(Boolean).join(" ");
        return { clipId: layer.clip.id, id, filter, curveTables: info.curveTables };
      }),
    [layers],
  );
  const filtersRef = React.useRef(filters);
  filtersRef.current = filters;

  // Keep the decoder/image pools in step with the active asset set.
  React.useEffect(() => {
    // Keyed by CLIP, not by asset. A source owns a playback position, and that belongs to the
    // clip: put the same asset on two layers at different times — a picture-in-picture of its
    // own source, a duplicated clip used as a backdrop — and one shared decoder was asked for
    // two positions per frame. Each call saw the cursor parked at the other's time, took the
    // seek path, flushed and closed every buffered frame, and returned null. Neither layer ever
    // accumulated a frame: both stayed black forever while the decoder thrashed at 60Hz.
    // Images stay keyed by asset — an <img> has no position, so sharing one is correct.
    const wantVideo = new Map<string, string>(); // clip id -> asset id
    const wantImage = new Set<string>();
    for (const layer of layers) {
      if (layer.asset.kind === "image") wantImage.add(layer.asset.id);
      else wantVideo.set(layer.clip.id, layer.asset.id);
    }
    for (const [id, source] of sourcesRef.current) {
      if (!wantVideo.has(id)) {
        source.park(); // drop decoded frames + the decoder; keep the parsed samples
        idleRef.current.set(id, source);
        sourcesRef.current.delete(id);
      }
    }
    for (const [clipId, assetId] of wantVideo) {
      if (sourcesRef.current.has(clipId)) continue;
      const parked = idleRef.current.get(clipId);
      if (parked) {
        idleRef.current.delete(clipId);
        sourcesRef.current.set(clipId, parked);
      } else {
        sourcesRef.current.set(clipId, new ProxyVideoSource(assetProxyUrl(assetId)));
      }
    }
    // Map preserves insertion order and re-parking re-inserts, so iterating it gives
    // least-recently-parked first — which is exactly the order `evictions` expects.
    const parked = [...idleRef.current].map(([id, source]) => ({ id, retainedBytes: source.retainedBytes }));
    for (const id of evictions(parked, IDLE_SOURCE_BYTE_BUDGET)) {
      idleRef.current.get(id)?.close();
      idleRef.current.delete(id);
    }
    dirtyRef.current = true;
    for (const id of wantImage) {
      if (!imagesRef.current.has(id)) {
        const img = new Image();
        img.crossOrigin = "anonymous"; // keep the canvas readable (scopes/capture) — asset URLs are cross-origin
        img.src = assetFileUrl(id);
        imagesRef.current.set(id, img);
      }
    }
    imagesRef.current.forEach((_img, id) => {
      if (!wantImage.has(id)) imagesRef.current.delete(id);
    });
  }, [layers]);

  React.useEffect(() => {
    return () => {
      sourcesRef.current.forEach((source) => source.close());
      sourcesRef.current.clear();
      idleRef.current.forEach((source) => source.close());
      idleRef.current.clear();
      imagesRef.current.clear();
    };
  }, []);

  React.useEffect(() => {
    let raf = 0;
    let lastPlayhead = Number.NaN;
    let lastSignature = "";
    let settled = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;

      const { playhead } = useEditorStore.getState();
      const currentLayers = layersRef.current;

      // A paused monitor was repainting 60 times a second to produce the same pixels. Resolve
      // what WOULD be drawn first; if it matches the last pass often enough to be settled, skip
      // the clear/draw entirely. Note mediaFor is still called — it is what drives decoding, so
      // skipping it would stall the frame we are waiting to settle on.
      const resolved = currentLayers.map((layer) =>
        mediaFor(layer, playhead, sourcesRef.current, imagesRef.current),
      );
      const signature = resolved
        .map((m, i) => `${currentLayers[i].clip.id}:${m ? mediaKey(m.source) : "-"}`)
        .join("|");

      // Report anything that will never produce a picture, once per asset, so the caller can
      // switch back to element playback rather than showing black. This MUST stay above the
      // settle check below: a proxy fails asynchronously, typically long after a paused canvas
      // has settled, and a settled canvas never re-enters the code past that early return — so
      // putting this after it meant the fallback silently never fired on a paused editor.
      for (const layer of currentLayers) {
        // Looked up per clip, reported per asset: the source is the clip's, but "this machine
        // cannot decode that proxy" is a property of the asset, and that is what the fallback
        // decision keys on.
        const source = sourcesRef.current.get(layer.clip.id);
        if (source && !source.ok && !reportedFailures.current.has(layer.asset.id)) {
          reportedFailures.current.add(layer.asset.id);
          onSourceFailedRef.current?.(layer.asset.id);
        }
      }

      if (playhead === lastPlayhead && signature === lastSignature && !dirtyRef.current) {
        if (settled >= SETTLE_FRAMES) return;
        settled += 1;
      } else {
        settled = 0;
      }
      lastPlayhead = playhead;
      lastSignature = signature;
      dirtyRef.current = false;

      ctx.clearRect(0, 0, width, height);

      const fill = fillModeRef.current;
      for (let i = 0; i < currentLayers.length; i++) {
        const layer = currentLayers[i];
        const media = resolved[i];
        if (!media) continue;
        const { source: img, w: mw, h: mh } = media;

        // 关键帧:按播放头在片段内的进度插值,画布合成才随预览动起来(拖拽手柄时 override 优先)。
        const tf = layer.transformOverride ?? sampleTransform(readTransform(layer.clip.transform), clipProgress(layer.clip, playhead));
        // Only the base layer (index 0) follows the sequence fill mode; overlays always cover.
        // "blur" paints a full-frame blurred cover backdrop, then the sharp contain-fit picture.
        const contain = i === 0 && fill !== "cover";
        if (i === 0 && fill === "blur") {
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
        ctx.filter = filtersRef.current[i]?.filter || "none";
        // Match Monitor's CSS: translate(x·50%, y·50%) of the frame, scale + rotate about center.
        ctx.translate(width / 2 + tf.x * 0.5 * width, height / 2 + tf.y * 0.5 * height);
        ctx.rotate((tf.rotation * Math.PI) / 180);
        ctx.scale(tf.scale, tf.scale);
        ctx.drawImage(img, -dw / 2, -dh / 2, dw, dh);
        ctx.restore();
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [width, height]);

  return (
    <>
      {filters.some((f) => f.curveTables) && (
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
          {filters.map(
            (f) =>
              f.curveTables && (
                <filter key={f.id} id={f.id} colorInterpolationFilters="sRGB">
                  <feComponentTransfer>
                    <feFuncR type="table" tableValues={f.curveTables.r} />
                    <feFuncG type="table" tableValues={f.curveTables.g} />
                    <feFuncB type="table" tableValues={f.curveTables.b} />
                  </feComponentTransfer>
                </filter>
              ),
          )}
        </svg>
      )}
      <canvas
        ref={(node) => {
          canvasRef.current = node;
          if (scopeCanvasRef) scopeCanvasRef.current = node;
        }}
        className={className}
        style={style}
      />
    </>
  );
}

/** How much encoded proxy to keep parked for sources that are off-screen. Two or three short
    clips' worth — enough that scrubbing over a cut is instant, not so much that a long timeline
    pins hundreds of megabytes. */
const IDLE_SOURCE_BYTE_BUDGET = 96 * 1024 * 1024;
/** Consecutive identical frames after which a paused canvas stops repainting. Frames keep
    arriving for a moment after a seek, so one identical pass is not enough to call it settled. */
const SETTLE_FRAMES = 3;

type Media = { source: CanvasImageSource; w: number; h: number };

/** Identifies WHICH picture a layer resolved to, so two passes can be compared without
    re-drawing. A VideoFrame's timestamp is exact; an <img> only changes when it finishes
    loading, which naturalWidth captures. */
function mediaKey(source: CanvasImageSource): string {
  if (typeof VideoFrame !== "undefined" && source instanceof VideoFrame) return `v${source.timestamp}`;
  if (source instanceof HTMLImageElement) return `i${source.naturalWidth}x${source.naturalHeight}`;
  return "?";
}

function mediaFor(
  layer: CompositorLayer,
  playhead: number,
  sources: Map<string, ProxyVideoSource>,
  images: Map<string, HTMLImageElement>,
): Media | null {
  if (layer.asset.kind === "image") {
    const img = images.get(layer.asset.id);
    if (!img || !img.complete || img.naturalWidth === 0) return null;
    return { source: img, w: img.naturalWidth, h: img.naturalHeight };
  }
  const source = sources.get(layer.clip.id);
  if (!source) return null;
  const speed = layer.clip.speed || 1;
  const mediaSec = layer.clip.src_in + (playhead - layer.clip.timeline_start) * speed;
  const frame = source.frameAt(mediaSec);
  if (!frame) return null;
  return { source: frame, w: frame.displayWidth, h: frame.displayHeight };
}
