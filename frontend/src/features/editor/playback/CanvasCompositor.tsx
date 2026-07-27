import React from "react";

import { assetFileUrl, assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { CURVES_FILTER_ID } from "@/features/editor/colorCurves";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import { ProxyVideoSource } from "@/features/editor/playback/ProxyVideoSource";
import { paintScene, type ScenePaintLayer } from "@/features/editor/playback/scenePaint";
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
  prewarmLayers,
  width,
  height,
  fillMode = "cover",
  className,
  style,
  onSourceFailed,
}: {
  layers: CompositorLayer[];
  /** Clips the playhead is about to reach (video only). Their decoders are kept alive and their
      first frame primed ahead of time, so crossing a cut into a cold proxy doesn't flash black
      while it fetches/parses/decodes. Never drawn — priming only. */
  prewarmLayers?: CompositorLayer[];
  width: number;
  height: number;
  /** Base-layer fit, matching the sequence reframe (overlay layers always cover). */
  fillMode?: "cover" | "contain" | "blur";
  className?: string;
  style?: React.CSSProperties;
  /** A proxy that cannot be decoded here. The caller should drop back to element playback —
      otherwise the layer simply never paints and the viewer sees an unexplained black frame. */
  onSourceFailed?: (assetId: string) => void;
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
  const prewarmRef = React.useRef(prewarmLayers);
  prewarmRef.current = prewarmLayers;
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
    // Upcoming clips keep their decoder too — created here so the fetch/parse starts ahead of the
    // playhead; the draw loop then primes their first frame. (Video only; images decode instantly.)
    for (const layer of prewarmLayers ?? []) {
      if (layer.asset.kind !== "image") wantVideo.set(layer.clip.id, layer.asset.id);
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
        // crossOrigin keeps the canvas readable (scopes/capture). But a crossOrigin load enforces
        // strict CORS, and some shells (Electron file:// → Origin "null") fail it even though the
        // video path's fetch() succeeds — leaving the base image permanently black with no fallback
        // (unlike video sources, which report failure and drop to element playback). So on error,
        // retry ONCE without crossOrigin: the picture paints (canvas becomes tainted → only readback
        // /scopes degrade, never the image itself). onload marks dirty so a late image repaints even
        // if the paused canvas had already settled on black.
        const url = assetFileUrl(id);
        img.crossOrigin = "anonymous";
        img.onload = () => {
          dirtyRef.current = true;
        };
        img.onerror = () => {
          if (img.crossOrigin != null) {
            img.crossOrigin = null;
            img.src = url;
          }
        };
        img.src = url;
        imagesRef.current.set(id, img);
      }
    }
    imagesRef.current.forEach((_img, id) => {
      if (!wantImage.has(id)) imagesRef.current.delete(id);
    });
  }, [layers, prewarmLayers]);

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

      // Prime the decoders of clips the playhead is about to reach, at their first frame, so a cut
      // into a never-seen proxy paints immediately instead of flashing black through the fetch/
      // parse/first-GOP window. Not drawn — priming only; frameAt is idempotent once buffered, so
      // this settles to a no-op. Kept above the settle early-return for the same reason mediaFor is:
      // it is what drives decoding, and a paused playhead parked just before a cut still needs it.
      for (const layer of prewarmRef.current ?? []) {
        const source = sourcesRef.current.get(layer.clip.id);
        if (source && source.ok) source.frameAt(layer.clip.src_in);
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

      // Resolve each visible layer to a finished paint spec, then hand the whole frame to the ONE
      // shared draw routine (also used by the offline export renderer, so preview == export pixels).
      // isBase is the layer's ORIGINAL index-0 position, not its position after nulls are dropped:
      // a base whose frame hasn't decoded yet must not let an overlay inherit base framing.
      const paintLayers: ScenePaintLayer[] = [];
      for (let i = 0; i < currentLayers.length; i++) {
        const media = resolved[i];
        if (!media) continue;
        const layer = currentLayers[i];
        // 关键帧:按播放头在片段内的进度插值,画布合成才随预览动起来(拖拽手柄时 override 优先)。
        const tf = layer.transformOverride ?? sampleTransform(readTransform(layer.clip.transform), clipProgress(layer.clip, playhead));
        paintLayers.push({ img: media.source, mw: media.w, mh: media.h, tf, filter: filtersRef.current[i]?.filter || "", isBase: i === 0 });
      }
      paintScene(ctx, paintLayers, { width, height, fillMode: fillModeRef.current });
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
      <canvas ref={canvasRef} className={className} style={style} />
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
