import React from "react";

import { assetPreviewUrl, assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { CURVES_FILTER_ID } from "@/features/editor/colorCurves";
import { readClipAppearance } from "@/features/editor/clipAppearance";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import type { ProxyVideoSource } from "@/features/editor/playback/ProxyVideoSource";
import { paintScene, type ScenePaintLayer } from "@/features/editor/playback/scenePaint";
import { VideoSourcePool, type WantedSource } from "@/features/editor/playback/videoSourcePool";
import { readTransform, type Transform } from "@/features/editor/TransformOverlay";
import { clipProgress, sampleTransform } from "@/features/editor/keyframes";
import { livePlayhead } from "@/features/editor/playback/playbackClock";
import { useEditorStore } from "@/features/editor/editorStore";

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
 * clips decode from their proxy via {@link VideoSourcePool} (one shared index + byte cache per
 * asset, one decoder cursor per clip, handed on across cuts); images blit from a cached
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
  // 素材共用样本表与样本数据缓存,片段各占一个解码游标,离场的游标留给同素材的下一段接着用;
  // 不在场的素材按占用字节停放(见 videoSourcePool)。
  const poolRef = React.useRef<VideoSourcePool | null>(null);
  if (!poolRef.current) poolRef.current = new VideoSourcePool(IDLE_SOURCE_BYTE_BUDGET);
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
    // 解码游标按**片段**分,不按素材:游标有自己的播放位置,而位置属于片段 —— 同一素材放在两层的不同
    // 时间上(画中画套自己的源、复制出来当背景的一段),共用一个游标就是每帧被要两个位置,两边来回
    // seek、谁也攒不下一帧,双双黑屏。样本表和样本数据则按素材共享(那是只读的)。
    // Images stay keyed by asset — an <img> has no position, so sharing one is correct.
    const wantVideo: WantedSource[] = [];
    const wantImage = new Set<string>();
    const playhead = useEditorStore.getState().playhead;
    for (const layer of layers) {
      if (layer.asset.kind === "image") wantImage.add(layer.asset.id);
      else wantVideo.push(wanted(layer, layer.clip.src_in + (playhead - layer.clip.timeline_start) * (layer.clip.speed || 1)));
    }
    // Upcoming clips keep their cursor too — assigned here so the fetch/decode starts ahead of the
    // playhead; the draw loop then primes their first frame. (Video only; images decode instantly.)
    for (const layer of prewarmLayers ?? []) {
      if (layer.asset.kind !== "image") wantVideo.push(wanted(layer, layer.clip.src_in));
    }
    poolRef.current?.sync(wantVideo);
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
        const url = assetPreviewUrl(id);
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
      poolRef.current?.close();
      poolRef.current = null;
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

      // 播放中按音频时钟插值(见 playbackClock):store 每 40ms 才写一次,直接读它画面就是 25fps 的阶梯。
      const playhead = livePlayhead();
      const currentLayers = layersRef.current;

      // A paused monitor was repainting 60 times a second to produce the same pixels. Resolve
      // what WOULD be drawn first; if it matches the last pass often enough to be settled, skip
      // the clear/draw entirely. Note mediaFor is still called — it is what drives decoding, so
      // skipping it would stall the frame we are waiting to settle on.
      const pool = poolRef.current;
      if (!pool) return;
      const resolved = currentLayers.map((layer) => mediaFor(layer, playhead, pool, imagesRef.current));
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
        const source = pool.sourceFor(sourceKey(layer));
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
        const source = pool.sourceFor(sourceKey(layer));
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
        paintLayers.push({
          img: media.source,
          mw: media.w,
          mh: media.h,
          tf,
          filter: filtersRef.current[i]?.filter || "",
          isBase: i === 0,
          appearance: readClipAppearance(layer.clip.effects),
        });
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

/** 不在场的素材最多停放这么多字节(样本表 + 缓存的样本数据)。按 Range 取之后每份素材只留几十秒
    的数据(按它自己的码率换算,见 ProxyMedia),这点预算能停住十几份素材,而不是从前的两三份整代理。 */
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

/** 一个解码源的身份 = 这个片段 **+ 它此刻指向的那份代理**。
 *
 * 只按 clip.id 缓存的话,代理重转过之后旧 source 里那份失败的解析结果会一直留着 ——
 * 「重新生成代理」成功了,画面照样黑着,只有刷新整页才活过来(而刷新之所以有效,正是因为
 * 它把这些 source 全丢了)。代理的指纹一变,键就变,旧的自然被淘汰、新的重新建。 */
function sourceKey(layer: CompositorLayer): string {
  return `${layer.clip.id}::${proxyMediaKey(layer)}`;
}

/** 素材 + 它此刻那份代理的指纹:同一个键共用一份样本表与缓存;代理重转过就是新的一份。 */
function proxyMediaKey(layer: CompositorLayer): string {
  const info = (layer.asset.media_info ?? {}) as { proxy_key?: string; proxy_status?: string };
  return `${layer.asset.id}:${info.proxy_key ?? ""}:${info.proxy_status ?? ""}`;
}

function wanted(layer: CompositorLayer, target: number): WantedSource {
  return { clipKey: sourceKey(layer), mediaKey: proxyMediaKey(layer), url: assetProxyUrl(layer.asset.id), target };
}

function mediaFor(
  layer: CompositorLayer,
  playhead: number,
  pool: VideoSourcePool,
  images: Map<string, HTMLImageElement>,
): Media | null {
  if (layer.asset.kind === "image") {
    const img = images.get(layer.asset.id);
    if (!img || !img.complete || img.naturalWidth === 0) return null;
    return { source: img, w: img.naturalWidth, h: img.naturalHeight };
  }
  const source: ProxyVideoSource | undefined = pool.sourceFor(sourceKey(layer));
  if (!source) return null;
  const speed = layer.clip.speed || 1;
  const mediaSec = layer.clip.src_in + (playhead - layer.clip.timeline_start) * speed;
  const frame = source.frameAt(mediaSec);
  if (!frame) return null;
  return { source: frame, w: frame.displayWidth, h: frame.displayHeight };
}
