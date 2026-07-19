import React from "react";

import { assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { ProxyVideoSource } from "@/features/editor/playback/ProxyVideoSource";
import { useEditorStore } from "@/stores/editorStore";

/**
 * S1 of the WebCodecs compositor: draws the base video track's current frame onto a
 * single canvas via {@link ProxyVideoSource}, instead of a `<video>` element. Runs its
 * own rAF loop reading the playhead straight from the store, so paint stays smooth and
 * decoupled from React re-renders. Falls back (via onError) when the proxy can't decode.
 */
export function CanvasStage({
  clip,
  asset,
  width,
  height,
  className,
  style,
  onError,
}: {
  clip: Clip;
  asset: Asset;
  width: number;
  height: number;
  className?: string;
  style?: React.CSSProperties;
  onError?: () => void;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const sourceRef = React.useRef<ProxyVideoSource | null>(null);

  // One decoder per proxy asset; recreated when the underlying asset changes.
  React.useEffect(() => {
    const source = new ProxyVideoSource(assetProxyUrl(asset.id));
    sourceRef.current = source;
    source.ready.catch(() => onError?.());
    return () => {
      source.close();
      sourceRef.current = null;
    };
    // onError is stable enough; re-subscribing on its identity would thrash the decoder.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset.id]);

  React.useEffect(() => {
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const source = sourceRef.current;
      if (!canvas || !source) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;

      const { playhead } = useEditorStore.getState();
      const speed = clip.speed || 1;
      const mediaSec = clip.src_in + (playhead - clip.timeline_start) * speed;
      const frame = source.frameAt(mediaSec);
      if (!frame) return;
      // objectFit: cover — scale to fill, center-crop the overflow.
      const scale = Math.max(width / frame.displayWidth, height / frame.displayHeight);
      const dw = frame.displayWidth * scale;
      const dh = frame.displayHeight * scale;
      ctx.drawImage(frame, (width - dw) / 2, (height - dh) / 2, dw, dh);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [clip.id, clip.src_in, clip.timeline_start, clip.speed, width, height]);

  return <canvas ref={canvasRef} className={className} style={style} />;
}
