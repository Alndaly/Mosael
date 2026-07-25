import React from "react";

import { assetFileUrl, assetProxyUrl, type Asset, type Clip } from "@/api/client";
import { computeFilters, type ClipEffects } from "@/features/editor/monitorFilters";
import { clipProgress, sampleTransform } from "@/features/editor/keyframes";
import { readTransform, transformCss, type Transform } from "@/features/editor/TransformOverlay";

/**
 * One video/image clip as a free canvas element: filled to its transform box (objectFit cover),
 * positioned/sized/rotated by its transform, self-syncing to the playhead. Muted — the base
 * video track carries preview audio. `transformOverride` lets the canvas handles drive it live.
 */
export function MonitorElement({
  clip,
  asset,
  playhead,
  playing,
  playbackRate,
  transformOverride,
}: {
  clip: Clip;
  asset: Asset;
  playhead: number;
  playing: boolean;
  playbackRate: number;
  transformOverride?: Transform | null;
}) {
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const loadedRef = React.useRef<string | null>(null);
  const isImage = asset.kind === "image";
  // 关键帧激活时,transform 随 playhead 在片段内的进度插值——预览里"动起来";
  // 拖拽手柄期间 transformOverride 优先(直接操纵先于动画)。
  const tf = transformOverride ?? sampleTransform(readTransform(clip.transform), clipProgress(clip, playhead));
  const { cssFilter, curveTables } = computeFilters((clip.effects ?? {}) as ClipEffects);
  const filterId = `mel-curves-${clip.id}`;
  const filter = [cssFilter, curveTables ? `url(#${filterId})` : ""].filter(Boolean).join(" ") || undefined;
  const style: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
    filter,
    ...transformCss(tf),
  };

  React.useEffect(() => {
    if (isImage) return;
    const video = videoRef.current;
    if (!video) return;
    // 优先放 720p 短 GOP 代理(就是给预览用的):解码/跳转都轻,和播放头同步时不会因为解不动
    // 全分辨率原片而一顿一顿(常见于把导出的视频再拖回时间线对比)。代理没就绪才回落原片。
    const src =
      (asset.media_info as { proxy_status?: string } | undefined)?.proxy_status === "ready"
        ? assetProxyUrl(asset.id)
        : assetFileUrl(asset.id);
    if (loadedRef.current !== src) {
      loadedRef.current = src;
      video.src = src;
    }
    const speed = clip.speed || 1;
    const desired = clip.src_in + (playhead - clip.timeline_start) * speed;
    if (Math.abs(video.currentTime - desired) > 0.18) video.currentTime = desired;
    video.playbackRate = playbackRate * speed;
    if (playing && video.paused) video.play().catch(() => undefined);
    else if (!playing && !video.paused) video.pause();
  }, [playhead, playing, playbackRate, clip.src_in, clip.timeline_start, clip.speed, asset.id, isImage]);

  return (
    <>
      {curveTables && (
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
          <filter id={filterId} colorInterpolationFilters="sRGB">
            <feComponentTransfer>
              <feFuncR type="table" tableValues={curveTables.r} />
              <feFuncG type="table" tableValues={curveTables.g} />
              <feFuncB type="table" tableValues={curveTables.b} />
            </feComponentTransfer>
          </filter>
        </svg>
      )}
      {isImage ? (
        <img className="absolute inset-0 z-[1] h-full w-full bg-black object-contain" src={assetFileUrl(asset.id)} alt="" style={style} />
      ) : (
        <video ref={videoRef} className="absolute inset-0 z-[1] h-full w-full bg-black object-contain" style={style} muted playsInline preload="auto" />
      )}
    </>
  );
}
