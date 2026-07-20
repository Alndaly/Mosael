import React from "react";
import { Activity, Maximize2, Pause, Play, Repeat, SkipBack, SkipForward, StepBack, StepForward, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl, type Asset, type Clip, type Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { clipEnd, formatTimecode, sequenceDuration } from "@/domain/timeline/geometry";
import { CURVES_FILTER_ID, colorCurvesTables, type ColorCurves } from "@/features/editor/colorCurves";
import { AudioElement } from "@/features/editor/AudioElement";
import { MonitorElement } from "@/features/editor/MonitorElement";
import { CanvasCompositor, type CompositorLayer } from "@/features/editor/playback/CanvasCompositor";
import { WebAudioMixer, type AudioSourceSpec } from "@/features/editor/playback/WebAudioMixer";
import { compositorSupported, useCompositorEnabled } from "@/features/editor/playback/compositorFlag";
import { ScopesFloat } from "@/features/editor/ScopesFloat";
import { readSubtitleStyle, subtitleCss } from "@/features/editor/subtitleStyle";
import { TransformOverlay, readTransform, transformCss, type Transform } from "@/features/editor/TransformOverlay";
import { useEditorStore } from "@/stores/editorStore";

/**
 * MVP preview: an rAF clock drives the playhead; the <video> element renders
 * whichever video-track clip sits under it and is continuously re-synced.
 * Gaps render as black, matching export semantics.
 */
/** CSS approximations of the backend FFmpeg filter presets (render_plan.FILTER_PRESETS). */
const FILTER_CSS: Record<string, string> = {
  bw: "grayscale(1)",
  warm: "sepia(0.22) saturate(1.15)",
  cool: "hue-rotate(-8deg) saturate(1.1) brightness(1.02)",
  vivid: "saturate(1.4) contrast(1.06)",
  fade: "saturate(0.75) contrast(0.9) brightness(1.05)",
};

export function Monitor({
  sequence,
  assets,
  onSetTransform,
}: {
  sequence: Sequence;
  assets: Asset[];
  onSetTransform?: (clipId: string, transform: Transform) => void;
}) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds);
  const playing = useEditorStore((state) => state.playing);
  const loop = useEditorStore((state) => state.loop);
  const playbackRate = useEditorStore((state) => state.playbackRate);
  const volume = useEditorStore((state) => state.volume);
  const masterMuted = useEditorStore((state) => state.muted);
  const { setPlayhead, setPlaying, togglePlaying, toggleLoop, cyclePlaybackRate, setVolume, toggleMuted } =
    useEditorStore.getState();
  const [showScopes, setShowScopes] = React.useState(false);
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const monitorStageRef = React.useRef<HTMLDivElement | null>(null);
  // TEMP: measure the rendered subtitle element — it IS in the DOM (diagnostic says active:YES)
  // but isn't visible, so we need its computed style/geometry. Remove with the overlay.
  const subtitleRef = React.useRef<HTMLDivElement | null>(null);
  const [subMetrics, setSubMetrics] = React.useState("");
  const scrubRef = React.useRef<HTMLDivElement | null>(null);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const loadedAssetRef = React.useRef<string | null>(null);

  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const videoTracks = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((item) => item.kind === "video")
        .sort((a, b) => a.position - b.position),
    [sequence],
  );
  // PR/DaVinci z-order: the topmost timeline video track renders on top. videoTracks is sorted by
  // position ascending (top row first), so the base (bottom layer, full frame) is the LAST track;
  // tracks above composite upward, rendered so the top row (index 0) is last in the DOM = on top.
  const videoClips = React.useMemo(
    () => [...(videoTracks[videoTracks.length - 1]?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start),
    [videoTracks],
  );
  const overlayClips = React.useMemo(
    () =>
      videoTracks
        .slice(0, -1)
        .reverse()
        .flatMap((track) => [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start)),
    [videoTracks],
  );
  const audioTracks = React.useMemo(
    () => (sequence.tracks ?? []).filter((item) => item.kind === "audio"),
    [sequence],
  );
  const subtitleClips = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((item) => item.kind === "subtitle" && !item.muted)
        .flatMap((track) => track.clips ?? []),
    [sequence],
  );
  const totalDuration = React.useMemo(
    () => sequenceDuration((sequence.tracks ?? []).flatMap((track) => track.clips ?? [])),
    [sequence],
  );

  const activeClip =
    videoClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeAsset = activeClip?.asset_id ? (assetById.get(activeClip.asset_id) ?? null) : null;
  // 改画幅:画框宽高比 + 填充模式(cover 裁剪 / contain 留黑边 / blur 模糊背景)。
  const fillMode = ((sequence.reframe as { fill_mode?: string } | undefined)?.fill_mode ?? "cover") as
    | "cover"
    | "contain"
    | "blur";
  const frameStyle = React.useMemo<React.CSSProperties>(
    () => ({
      aspectRatio: `${sequence.width} / ${sequence.height}`,
      ["--frame-ar" as string]: sequence.width / Math.max(1, sequence.height),
    }),
    [sequence.width, sequence.height],
  );
  const fitStyle: React.CSSProperties = { objectFit: fillMode === "cover" ? "cover" : "contain" };
  const bgVideoRef = React.useRef<HTMLVideoElement | null>(null);
  // On-canvas direct manipulation: while dragging a handle, `draft` overrides the selected clip's
  // saved transform so the media tracks the box live; committed on release via onSetTransform.
  // (selectedActive + clipTransformStyle are derived below, after the overlay elements.)
  const [draft, setDraft] = React.useState<Transform | null>(null);
  // Time of the last transform-drag movement — the click that *ends* a drag would otherwise
  // bubble to the frame's click-to-play; ignore clicks within a short window after a drag.
  const tfInteractRef = React.useRef(0);
  // Keep the draft until the fresh sequence lands (same anti-flicker pattern as timeline drags),
  // otherwise clearing the draft on release snaps the box back to the stale saved transform.
  const tfSettleRef = React.useRef(false);
  const activeSubtitle =
    subtitleClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  // TEMP diagnostic: why is the rendered subtitle invisible? Report its computed paint properties
  // and geometry relative to the frame. Remove together with the overlay below.
  React.useEffect(() => {
    const element = subtitleRef.current;
    if (!element) {
      setSubMetrics(activeSubtitle ? "el:missing" : "");
      return;
    }
    const style = window.getComputedStyle(element);
    const box = element.getBoundingClientRect();
    const frame = stageRef.current?.getBoundingClientRect();
    setSubMetrics(
      `font=${style.fontSize} color=${style.color} bg=${style.backgroundColor} op=${style.opacity} ` +
        `vis=${style.visibility} disp=${style.display} z=${style.zIndex} ` +
        `box=${Math.round(box.width)}x${Math.round(box.height)}` +
        (frame
          ? ` at=${Math.round(box.left - frame.left)},${Math.round(box.top - frame.top)} frame=${Math.round(frame.width)}x${Math.round(frame.height)}`
          : ""),
    );
  }, [activeSubtitle, playhead, sequence.subtitle_style, sequence.width]);
  const activeEffects = (activeClip?.effects ?? {}) as {
    filter?: string;
    color?: Record<string, number> & { curves?: ColorCurves };
  };
  const { cssFilter, vignette, curveTables } = React.useMemo(() => {
    const parts: string[] = [];
    const preset = FILTER_CSS[String(activeEffects.filter ?? "")];
    if (preset) parts.push(preset);
    const grade = activeEffects.color ?? {};
    const v = (key: string) => Math.max(-1, Math.min(1, Number(grade[key]) || 0));
    // CSS 近似导出端的 FFmpeg 公式(色阶曲线/锐化无法用 CSS 表达,仅导出生效)。
    const brightFactor = (1 + v("brightness")) * (1 + v("exposure") / 2);
    if (Math.abs(brightFactor - 1) > 0.005) parts.push(`brightness(${brightFactor.toFixed(3)})`);
    if (v("contrast")) parts.push(`contrast(${(1 + v("contrast") * 0.6).toFixed(3)})`);
    if (v("gamma")) parts.push(`brightness(${(1 + v("gamma") * 0.25).toFixed(3)})`);
    const sat = 1 + v("saturation") + v("vibrance") * 0.5;
    if (Math.abs(sat - 1) > 0.005) parts.push(`saturate(${Math.max(0, sat).toFixed(3)})`);
    if (v("hue")) parts.push(`hue-rotate(${(v("hue") * 180).toFixed(1)}deg)`);
    const w = v("temperature");
    if (w > 0) parts.push(`sepia(${(w * 0.25).toFixed(3)})`);
    else if (w < 0) parts.push(`hue-rotate(${(w * 12).toFixed(1)}deg) saturate(${(1 - w * 0.08).toFixed(3)})`);
    if (v("tint")) parts.push(`hue-rotate(${(v("tint") * -8).toFixed(1)}deg)`);
    const fadeAmount = Math.max(0, v("fade"));
    if (fadeAmount) parts.push(`contrast(${(1 - fadeAmount * 0.25).toFixed(3)}) brightness(${(1 + fadeAmount * 0.08).toFixed(3)})`);
    // 色调曲线无法用 CSS filter 函数表达 → 引用一次性渲染的 SVG feComponentTransfer 滤镜精确查表。
    const tables = colorCurvesTables(grade.curves);
    if (tables) parts.push(`url(#${CURVES_FILTER_ID})`);
    return { cssFilter: parts.join(" "), vignette: Math.max(0, v("vignette")), curveTables: tables };
  }, [activeEffects.filter, activeEffects.color]);
  const isImage = activeAsset?.kind === "image";
  // WebCodecs compositor (opt-in): composite every active video/image clip onto one canvas.
  // The base <video> stays mounted (hidden) for audio until WebAudio mixing lands in S3.
  const compositorOn = useCompositorEnabled() && compositorSupported();
  // Active audio played via <AudioElement> (non-compositor path): every audio-track clip PLUS
  // every overlay video-track clip's audio. The bottom "base" video track's audio is carried by
  // the base <video> element, so a clip on ANY track sounds — not just the base track.
  const activeAudioClips = React.useMemo(() => {
    const list: { clip: Clip; trackMuted: boolean }[] = [];
    for (const track of videoTracks.slice(0, -1)) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id || assetById.get(clip.asset_id)?.kind !== "video") continue;
        if (playhead >= clip.timeline_start && playhead < clipEnd(clip)) list.push({ clip, trackMuted: Boolean(track.muted) });
      }
    }
    for (const track of audioTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id) continue;
        if (playhead >= clip.timeline_start && playhead < clipEnd(clip)) list.push({ clip, trackMuted: Boolean(track.muted) });
      }
    }
    return list;
  }, [videoTracks, audioTracks, assetById, playhead]);
  // Every active clip on an overlay video track (V2+), z-ordered by track — each renders as a
  // free canvas element (MonitorElement self-syncs). The base V1 clip stays the audio/scopes/blur owner.
  const activeOverlayClips = React.useMemo(
    () => overlayClips.filter((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)),
    [overlayClips, playhead],
  );
  // The selected on-screen element (base V1 or any active overlay) gets the transform handles.
  const selectedActive = React.useMemo(
    () => [activeClip, ...activeOverlayClips].find((clip) => clip && selectedClipIds.includes(clip.id)) ?? null,
    [activeClip, activeOverlayClips, selectedClipIds],
  );
  React.useEffect(() => setDraft(null), [selectedActive?.id]);
  // Drop the committed draft only once the fresh sequence has propagated (armed on commit), so the
  // box never flashes back to the pre-drag transform between release and the server round-trip.
  React.useEffect(() => {
    if (tfSettleRef.current) {
      tfSettleRef.current = false;
      setDraft(null);
    }
  }, [sequence]);
  const draftFor = (clipId: string | undefined) => (draft && selectedActive?.id === clipId ? draft : null);
  const clipTransformStyle = React.useMemo<React.CSSProperties>(
    () => transformCss(draftFor(activeClip?.id) ?? readTransform(activeClip?.transform)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft, selectedActive?.id, activeClip?.id, activeClip?.transform],
  );

  // Active video/image clips in z-order (base first = bottom, overlays bottom→top) as
  // compositor layers, each carrying its live drag transform. Memoised so the compositor's
  // decoder pool doesn't churn on every playhead tick.
  const compositorLayers = React.useMemo<CompositorLayer[]>(() => {
    const layers: CompositorLayer[] = [];
    for (const clip of [activeClip, ...activeOverlayClips]) {
      if (!clip?.asset_id) continue;
      const asset = assetById.get(clip.asset_id);
      if (!asset || (asset.kind !== "video" && asset.kind !== "image")) continue;
      layers.push({ clip, asset, transformOverride: draft && selectedActive?.id === clip.id ? draft : null });
    }
    return layers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeClip, activeOverlayClips, assetById, draft, selectedActive?.id]);
  // Only take the canvas path when every active clip can be drawn there (image, or a
  // video whose proxy is ready); otherwise fall back wholesale to the element preview.
  const compositorActive =
    compositorOn &&
    compositorLayers.length > 0 &&
    compositorLayers.every(
      (l) =>
        l.asset.kind === "image" ||
        (l.asset.media_info as { proxy_status?: string } | undefined)?.proxy_status === "ready",
    );
  // EVERY audio-bearing clip (base video-track video clips + all audio-track clips) fed to the
  // WebAudio mixer, which filters by the live playhead itself. Passing the full set — not just
  // the currently-active clips — means a clip that comes up under the advancing playhead is
  // already in the mixer's list, so it starts on time instead of one render late.
  const audioSources = React.useMemo<AudioSourceSpec[]>(() => {
    const list: AudioSourceSpec[] = [];
    for (const track of videoTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id || assetById.get(clip.asset_id)?.kind !== "video") continue; // images have no audio
        list.push({
          key: clip.id, assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out,
          timelineStart: clip.timeline_start, speed: clip.speed || 1, gain: clip.gain ?? 1,
          muted: Boolean(clip.muted), trackMuted: Boolean(track.muted),
        });
      }
    }
    for (const track of audioTracks) {
      for (const clip of track.clips ?? []) {
        if (!clip.asset_id) continue;
        list.push({
          key: clip.id, assetId: clip.asset_id, srcIn: clip.src_in, srcOut: clip.src_out,
          timelineStart: clip.timeline_start, speed: clip.speed || 1, gain: clip.gain ?? 1,
          muted: Boolean(clip.muted), trackMuted: Boolean(track.muted),
        });
      }
    }
    return list;
  }, [videoTracks, audioTracks, assetById]);

  // Playback clock. Interval-based (not rAF) so it keeps running when the
  // window is occluded or backgrounded — audio keeps playing there too.
  // While the compositor is active the WebAudio mixer's AudioContext is the master
  // clock instead, so this one stands down to avoid two clocks fighting.
  React.useEffect(() => {
    if (!playing || compositorActive) return;
    let last = performance.now();
    const interval = window.setInterval(() => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      const state = useEditorStore.getState();
      const next = state.playhead + dt * state.playbackRate;
      if (totalDuration > 0 && next >= totalDuration) {
        if (state.loop) {
          state.setPlayhead(0);
          return;
        }
        state.setPlayhead(totalDuration);
        state.setPlaying(false);
        return;
      }
      state.setPlayhead(next);
    }, 40);
    return () => window.clearInterval(interval);
  }, [playing, totalDuration, compositorActive]);

  // Keep the video element in lockstep with the clock.
  React.useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!activeClip || !activeAsset || isImage) {
      if (!video.paused) video.pause();
      return;
    }
    if (loadedAssetRef.current !== activeAsset.id) {
      loadedAssetRef.current = activeAsset.id;
      video.src = assetFileUrl(activeAsset.id);
    }
    const clipSpeed = activeClip.speed || 1;
    const desired = activeClip.src_in + (playhead - activeClip.timeline_start) * clipSpeed;
    if (Math.abs(video.currentTime - desired) > 0.18) {
      video.currentTime = desired;
    }
    video.playbackRate = playbackRate * clipSpeed;
    // The clip carries its own audio (like PR/DaVinci): fold its gain/mute into the master volume.
    const clipGain = activeClip.muted ? 0 : Math.min(1, Math.max(0, activeClip.gain ?? 1));
    video.volume = (masterMuted ? 0 : volume) * clipGain;
    if (playing && video.paused) {
      video.play().catch(() => undefined);
    } else if (!playing && !video.paused) {
      video.pause();
    }
    // 模糊背景:第二路静音视频松同步(装饰用,不必逐帧精确)
    const bg = bgVideoRef.current;
    if (bg && fillMode === "blur") {
      if (bg.src !== video.src) bg.src = video.src;
      if (Math.abs(bg.currentTime - desired) > 0.3) bg.currentTime = desired;
      bg.playbackRate = video.playbackRate;
      bg.muted = true;
      if (playing && bg.paused) bg.play().catch(() => undefined);
      else if (!playing && !bg.paused) bg.pause();
    }
  }, [playhead, playing, activeClip, activeAsset, isImage, playbackRate, volume, masterMuted]);

  const frameStep = 1 / (sequence.fps || 30);
  const seekFromScrub = (clientX: number) => {
    const rect = scrubRef.current?.getBoundingClientRect();
    if (!rect || totalDuration <= 0) return;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    setPlayhead(ratio * totalDuration);
  };
  const handleScrub = (event: React.PointerEvent<HTMLDivElement>) => {
    seekFromScrub(event.clientX);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // synthetic/stale pointers cannot be captured; dragging still works while pressed
    }
  };
  const toggleFullscreen = () => {
    // Fullscreen the stage (not the frame): it's a size container that centers the frame, so the
    // frame's cq-based min(100cqw, 100cqh×ar) sizing now resolves against the SCREEN and stays
    // 16:9 (letterboxed), instead of the frame filling the screen and object-fit cropping it.
    const stage = monitorStageRef.current;
    if (!stage) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void stage.requestFullscreen().catch(() => undefined);
  };
  const playToggle = () => {
    if (!playing && totalDuration > 0 && playhead >= totalDuration) setPlayhead(0);
    togglePlaying();
  };
  // Frame click toggles play — but not the click that just ended a transform drag.
  const onFrameClick = () => {
    if (performance.now() - tfInteractRef.current < 300) return;
    playToggle();
  };

  return (
    <div className="monitor-stack">
      {/* Scopes as a draggable floating window (position: fixed), never covering the picture. */}
      {showScopes && <ScopesFloat videoRef={videoRef} filter={cssFilter} onClose={() => setShowScopes(false)} />}
      {/* Audio path: the WebAudio mixer owns everything (base clip + audio tracks) while the
          compositor is active; otherwise one <audio> per active audio-track clip. */}
      {compositorActive ? (
        <WebAudioMixer sources={audioSources} totalDuration={totalDuration} />
      ) : (
        activeAudioClips.map(({ clip, trackMuted }) => (
          <AudioElement
            key={clip.id}
            clip={clip}
            playing={playing}
            playhead={playhead}
            playbackRate={playbackRate}
            volume={volume}
            masterMuted={masterMuted}
            trackMuted={trackMuted}
          />
        ))
      )}
      {/* 曲线预览滤镜:逐通道 feComponentTransfer 查表,cssFilter 里以 url(#id) 引用。 */}
      {curveTables && (
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
          <filter id={CURVES_FILTER_ID} colorInterpolationFilters="sRGB">
            <feComponentTransfer>
              <feFuncR type="table" tableValues={curveTables.r} />
              <feFuncG type="table" tableValues={curveTables.g} />
              <feFuncB type="table" tableValues={curveTables.b} />
            </feComponentTransfer>
          </filter>
        </svg>
      )}
      <div className="monitor-stage" ref={monitorStageRef}>
        <div className="monitor-frame-wrap" ref={stageRef} onClick={onFrameClick} style={frameStyle}>
          {fillMode === "blur" && activeClip && (
            <div className="monitor-blur-bg" aria-hidden>
              {isImage && activeAsset ? (
                <img className="monitor-blur-media" src={assetFileUrl(activeAsset.id)} alt="" />
              ) : (
                <video ref={bgVideoRef} className="monitor-blur-media" muted playsInline preload="auto" />
              )}
            </div>
          )}
          {/* Base video: hidden while the compositor is drawing (canvas covers it) but kept
              mounted so it still carries preview audio until WebAudio mixing lands in S3. */}
          <video
            ref={videoRef}
            className="monitor-video"
            style={{
              display: activeClip && !isImage ? "block" : "none",
              opacity: compositorActive ? 0 : undefined,
              filter: cssFilter || undefined,
              ...fitStyle,
              ...clipTransformStyle,
            }}
            muted={compositorActive}
            playsInline
            preload="auto"
          />
          {activeClip && isImage && activeAsset && !compositorActive && (
            <img
              className="monitor-video"
              src={assetFileUrl(activeAsset.id)}
              alt=""
              style={{ filter: cssFilter || undefined, ...fitStyle, ...clipTransformStyle }}
            />
          )}
          {compositorActive && (
            <CanvasCompositor
              layers={compositorLayers}
              width={sequence.width}
              height={sequence.height}
              fillMode={fillMode}
              className="monitor-video"
              style={fitStyle}
            />
          )}
          {!activeClip && (
            <div className="monitor-blank">
              <span className="monitor-blank-hint">{t("monitorBlankHint")}</span>
            </div>
          )}
          {vignette > 0 && (
            <div
              className="monitor-vignette"
              style={{ boxShadow: `inset 0 0 ${60 + vignette * 120}px ${vignette * 60}px rgba(0,0,0,${0.35 + vignette * 0.4})` }}
            />
          )}
          {activeSubtitle?.text_override && (
            <div
              ref={subtitleRef}
              className="monitor-subtitle"
              style={subtitleCss(readSubtitleStyle(sequence.subtitle_style as Record<string, unknown>), sequence.width)}
            >
              {activeSubtitle.text_override}
            </div>
          )}
          {/* TEMP diagnostic — subtitles don't render for some sequences and every static check
              (data, serialisation, range math, CSS) says they should, so we need the runtime
              decision. Shown automatically in dev (never in a production build); set
              localStorage['mibu.subdebug']='0' to silence it. Remove once diagnosed. */}
          {typeof window !== "undefined" &&
            window.localStorage.getItem("mibu.subdebug") !== "0" &&
            (import.meta.env.DEV || window.localStorage.getItem("mibu.subdebug") === "1") && (
            <div
              style={{
                position: "absolute",
                top: 4,
                left: 4,
                zIndex: 50,
                background: "rgba(0,0,0,0.85)",
                color: "#4ade80",
                font: "11px ui-monospace, monospace",
                padding: "3px 6px",
                borderRadius: 4,
                pointerEvents: "none",
                whiteSpace: "pre-wrap",
                maxWidth: "92%",
                lineHeight: 1.5,
              }}
            >
              {`subs:${subtitleClips.length} t:${playhead.toFixed(2)} active:${activeSubtitle?.text_override ? "YES" : "NULL"} comp:${String(compositorActive)}`}
              {activeSubtitle == null &&
                subtitleClips.length > 0 &&
                ` near:${subtitleClips
                  .map((c) => `${c.timeline_start.toFixed(1)}-${clipEnd(c).toFixed(1)}`)
                  .slice(0, 4)
                  .join(",")}`}
              {subMetrics && `\n${subMetrics}`}
            </div>
          )}
          {/* Overlay clips as free elements — skipped when the compositor draws them all on canvas. */}
          {!compositorActive &&
            activeOverlayClips.map((clip) => {
              const asset = clip.asset_id ? assetById.get(clip.asset_id) : null;
              if (!asset) return null;
              return (
                <MonitorElement
                  key={clip.id}
                  clip={clip}
                  asset={asset}
                  playhead={playhead}
                  playing={playing}
                  playbackRate={playbackRate}
                  transformOverride={draftFor(clip.id)}
                />
              );
            })}
          {selectedActive && onSetTransform && (
            <div className="monitor-tf-layer" onClick={(event) => event.stopPropagation()}>
              <TransformOverlay
                frameRef={stageRef}
                transform={draft ?? readTransform(selectedActive.transform)}
                onChange={(tf) => {
                  tfInteractRef.current = performance.now();
                  setDraft(tf);
                }}
                onCommit={(next) => {
                  tfInteractRef.current = performance.now();
                  tfSettleRef.current = true; // hold the draft until the fresh sequence arrives
                  onSetTransform(selectedActive.id, next);
                }}
              />
            </div>
          )}
        </div>
      </div>
      <div
        className="monitor-scrub"
        ref={scrubRef}
        onPointerDown={handleScrub}
        onPointerMove={(event) => event.buttons & 1 && seekFromScrub(event.clientX)}
      >
        <div
          className="monitor-scrub-fill"
          style={{ width: totalDuration > 0 ? `${(Math.min(playhead, totalDuration) / totalDuration) * 100}%` : "0%" }}
        />
      </div>
      <div className="monitor-transport">
        <div className="monitor-buttons">
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(0)} aria-label={t("monStart")}>
            <SkipBack size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(Math.max(0, playhead - frameStep))} aria-label={t("monFrameBack")}>
            <StepBack size={14} />
          </Button>
          <Button variant="secondary" size="icon-sm" className="monitor-play" onClick={playToggle} aria-label={t("playPause")}>
            {playing ? <Pause size={14} /> : <Play size={14} className="monitor-play-icon" />}
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(Math.min(totalDuration, playhead + frameStep))} aria-label={t("monFrameForward")}>
            <StepForward size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(totalDuration)} aria-label={t("monEnd")}>
            <SkipForward size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className={loop ? "monitor-active" : undefined}
            onClick={toggleLoop}
            aria-label={t("monLoop")}
          >
            <Repeat size={13} />
          </Button>
          <button type="button" className="monitor-rate timecode" onClick={cyclePlaybackRate} aria-label={t("monRate")}>
            {playbackRate}x
          </button>
        </div>
        <div className="monitor-timecode timecode">
          {formatTimecode(playhead)}
          <span className="monitor-total"> / {formatTimecode(totalDuration)}</span>
        </div>
        <div className="monitor-buttons">
          <Button
            variant="ghost"
            size="icon-sm"
            className={showScopes ? "monitor-active" : undefined}
            onClick={() => setShowScopes((on) => !on)}
            aria-label={t("scopes")}
            title={t("scopes")}
          >
            <Activity size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={toggleMuted} aria-label={t("monMute")}>
            {masterMuted || volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </Button>
          <Slider
            className="monitor-volume"
            min={0}
            max={1}
            step={0.05}
            value={[masterMuted ? 0 : volume]}
            onValueChange={([value]) => setVolume(value)}
            aria-label={t("monVolume")}
          />
          <Button variant="ghost" size="icon-sm" onClick={toggleFullscreen} aria-label={t("monFullscreen")}>
            <Maximize2 size={13} />
          </Button>
        </div>
      </div>
    </div>
  );
}
