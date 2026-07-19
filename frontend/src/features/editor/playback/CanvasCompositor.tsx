import React from "react";

import { assetFileUrl, assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { CURVES_FILTER_ID } from "@/features/editor/colorCurves";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import { ProxyVideoSource } from "@/features/editor/playback/ProxyVideoSource";
import { readTransform, type Transform } from "@/features/editor/TransformOverlay";
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
  className,
  style,
}: {
  layers: CompositorLayer[];
  width: number;
  height: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const sourcesRef = React.useRef<Map<string, ProxyVideoSource>>(new Map());
  const imagesRef = React.useRef<Map<string, HTMLImageElement>>(new Map());
  const layersRef = React.useRef(layers);
  layersRef.current = layers;

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
    const wantVideo = new Set<string>();
    const wantImage = new Set<string>();
    for (const layer of layers) {
      if (layer.asset.kind === "image") wantImage.add(layer.asset.id);
      else wantVideo.add(layer.asset.id);
    }
    for (const [id, source] of sourcesRef.current) {
      if (!wantVideo.has(id)) {
        source.close();
        sourcesRef.current.delete(id);
      }
    }
    for (const id of wantVideo) {
      if (!sourcesRef.current.has(id)) sourcesRef.current.set(id, new ProxyVideoSource(assetProxyUrl(id)));
    }
    for (const id of wantImage) {
      if (!imagesRef.current.has(id)) {
        const img = new Image();
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
      imagesRef.current.clear();
    };
  }, []);

  React.useEffect(() => {
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;

      const { playhead } = useEditorStore.getState();
      ctx.clearRect(0, 0, width, height);

      const currentLayers = layersRef.current;
      for (let i = 0; i < currentLayers.length; i++) {
        const layer = currentLayers[i];
        const media = mediaFor(layer, playhead, sourcesRef.current, imagesRef.current);
        if (!media) continue;
        const { source: img, w: mw, h: mh } = media;

        const tf = layer.transformOverride ?? readTransform(layer.clip.transform);
        const cover = Math.max(width / mw, height / mh);
        const dw = mw * cover;
        const dh = mh * cover;

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
      <canvas ref={canvasRef} className={className} style={style} />
    </>
  );
}

type Media = { source: CanvasImageSource; w: number; h: number };

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
  const source = sources.get(layer.asset.id);
  if (!source) return null;
  const speed = layer.clip.speed || 1;
  const mediaSec = layer.clip.src_in + (playhead - layer.clip.timeline_start) * speed;
  const frame = source.frameAt(mediaSec);
  if (!frame) return null;
  return { source: frame, w: frame.displayWidth, h: frame.displayHeight };
}
