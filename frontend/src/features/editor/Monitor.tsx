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
  subtitleStyleOverride,
  assets,
  onSetTransform,
}: {
  sequence: Sequence;
  /** In-progress style from the subtitle panel, so dragging a slider previews live. */
  subtitleStyleOverride?: Record<string, unknown> | null;
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
  // Assets whose proxy turned out to be undecodable HERE — a codec this browser lacks, a
  // truncated file. proxy_status says the file exists, not that this machine can play it, so
  // that check alone let a decode failure show as a black frame. Falling back is per-asset and
  // sticky for the session — retrying every frame would flicker between black and the element.
  const [undecodable, setUndecodable] = React.useState<ReadonlySet<string>>(() => new Set());
  const markUndecodable = React.useCallback((assetId: string) => {
    setUndecodable((current) => (current.has(assetId) ? current : new Set(current).add(assetId)));
  }, []);
  // Which engine plays this SEQUENCE — deliberately not "what is under the playhead right now".
  //
  // Judging it per-frame meant every gap (no active layer) and every not-yet-proxied clip
  // switched engines mid-playback. WebAudioMixer is mounted only on the compositor path and
  // owns its AudioContext, so each switch closed the context and re-fetched and re-decoded
  // every clip's audio from scratch — an audible dropout at every gap, a fresh AudioContext
  // each time, and the master clock handed back and forth. It also defeated the idle decoder
  // pool: unmounting the compositor closes every parked source, so scrubbing over a gap threw
  // away exactly the cache that pool exists to keep.
  //
  // Audio cannot simply be decoupled from video here: the element path unmutes its <video>
  // whenever the compositor is off, so a mixer running alongside it would play everything
  // twice. The engine choice has to be one decision, and a stable one.
  const compositorAssets = React.useMemo(() => {
    const seen = new Map<string, Asset>();
    for (const track of videoTracks) {
      for (const clip of track.clips ?? []) {
        const asset = clip.asset_id ? assetById.get(clip.asset_id) : null;
        if (asset && (asset.kind === "video" || asset.kind === "image")) seen.set(asset.id, asset);
      }
    }
    return [...seen.values()];
  }, [videoTracks, assetById]);
  const compositorActive =
    compositorOn &&
    compositorAssets.every(
      (asset) =>
        asset.kind === "image" ||
        ((asset.media_info as { proxy_status?: string } | undefined)?.proxy_status === "ready" &&
          !undecodable.has(asset.id)),
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
    <div className="grid h-full grid-rows-[minmax(0,1fr)_auto_38px]">
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
      <div className="grid min-h-0 place-items-center p-3 [container-type:size] [&:fullscreen]:h-screen [&:fullscreen]:w-screen [&:fullscreen]:bg-black [&:fullscreen::backdrop]:bg-black" ref={monitorStageRef}>
        <div className="relative aspect-video max-h-full max-w-full overflow-hidden rounded-sm bg-black [container-type:inline-size] w-[min(100cqw,calc(100cqh*var(--frame-ar,1.7778)))] [:fullscreen_&]:rounded-none" ref={stageRef} onClick={onFrameClick} style={frameStyle}>
          {fillMode === "blur" && activeClip && (
            <div className="absolute inset-0 z-0 overflow-hidden" aria-hidden>
              {isImage && activeAsset ? (
                <img className="h-full w-full scale-[1.15] object-cover [filter:blur(28px)_brightness(0.75)]" src={assetFileUrl(activeAsset.id)} alt="" />
              ) : (
                <video ref={bgVideoRef} className="h-full w-full scale-[1.15] object-cover [filter:blur(28px)_brightness(0.75)]" muted playsInline preload="auto" />
              )}
            </div>
          )}
          {/* Base video: hidden while the compositor is drawing (canvas covers it) but kept
              mounted so it still carries preview audio until WebAudio mixing lands in S3. */}
          <video
            ref={videoRef}
            className="absolute inset-0 z-[1] h-full w-full bg-black object-contain"
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
              className="absolute inset-0 z-[1] h-full w-full bg-black object-contain"
              src={assetFileUrl(activeAsset.id)}
              alt=""
              style={{ filter: cssFilter || undefined, ...fitStyle, ...clipTransformStyle }}
            />
          )}
          {compositorActive && (
            <CanvasCompositor
              onSourceFailed={markUndecodable}
              layers={compositorLayers}
              width={sequence.width}
              height={sequence.height}
              fillMode={fillMode}
              className="absolute inset-0 z-[1] h-full w-full bg-black object-contain"
              style={fitStyle}
            />
          )}
          {!activeClip && (
            <div className="grid h-full w-full place-items-center bg-black object-contain">
              <span className="px-5 text-center text-[12.5px] text-[rgb(255_255_255/0.4)]">{t("monitorBlankHint")}</span>
            </div>
          )}
          {vignette > 0 && (
            <div
              className="pointer-events-none absolute inset-0 z-[2]"
              style={{ boxShadow: `inset 0 0 ${60 + vignette * 120}px ${vignette * 60}px rgba(0,0,0,${0.35 + vignette * 0.4})` }}
            />
          )}
          {activeSubtitle?.text_override && (
            <div
              className="pointer-events-none absolute bottom-[7%] left-1/2 z-[3] max-w-[86%] -translate-x-1/2 whitespace-pre-wrap rounded-md bg-[rgb(0_0_0/0.62)] px-2.5 py-[3px] text-center text-[clamp(12px,2.4cqw,20px)] leading-[1.45] text-white [text-shadow:0_1px_2px_rgb(0_0_0/0.7)]"
              style={subtitleCss(
                readSubtitleStyle(
                  (subtitleStyleOverride ?? sequence.subtitle_style) as Record<string, unknown>,
                ),
                sequence.width,
              )}
            >
              {activeSubtitle.text_override}
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
            <div className="pointer-events-none absolute inset-0 z-[4]" onClick={(event) => event.stopPropagation()}>
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
        className="group/scrub relative mx-2.5 flex h-3.5 cursor-pointer touch-none items-center before:absolute before:inset-x-0 before:h-[3px] before:rounded-sm before:bg-[rgb(255_255_255/0.16)] before:content-['']"
        ref={scrubRef}
        onPointerDown={handleScrub}
        onPointerMove={(event) => event.buttons & 1 && seekFromScrub(event.clientX)}
      >
        <div
          className="pointer-events-none relative h-[3px] rounded-sm bg-primary after:absolute after:-right-[5px] after:top-1/2 after:h-2.5 after:w-2.5 after:-translate-y-1/2 after:rounded-full after:bg-white after:opacity-0 after:transition-opacity after:duration-100 after:content-[''] group-hover/scrub:after:opacity-100"
          style={{ width: totalDuration > 0 ? `${(Math.min(playhead, totalDuration) / totalDuration) * 100}%` : "0%" }}
        />
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1.5 px-2 pb-[5px] pt-[3px] [&>div:last-child]:justify-end [&_button]:text-[#c6cbd2] [&_button:hover]:bg-[rgb(255_255_255/0.08)] [&_button:hover]:text-white">
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(0)} aria-label={t("monStart")}>
            <SkipBack size={14} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(Math.max(0, playhead - frameStep))} aria-label={t("monFrameBack")}>
            <StepBack size={14} />
          </Button>
          <Button variant="secondary" size="icon" className="h-7 w-7 rounded-full! bg-white! text-[#17181a]! transition-transform duration-[120ms] hover:scale-[1.06] hover:bg-white! hover:text-[#17181a]!" onClick={playToggle} aria-label={t("playPause")}>
            {playing ? <Pause size={14} /> : <Play size={14} className="ml-px" />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(Math.min(totalDuration, playhead + frameStep))} aria-label={t("monFrameForward")}>
            <StepForward size={14} />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setPlayhead(totalDuration)} aria-label={t("monEnd")}>
            <SkipForward size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={loop ? "bg-[rgb(255_255_255/0.1)]! text-primary!" : undefined}
            onClick={toggleLoop}
            aria-label={t("monLoop")}
          >
            <Repeat size={13} />
          </Button>
          <button type="button" className="timecode cursor-pointer rounded-md border border-[rgb(255_255_255/0.18)] bg-transparent px-[7px] py-0.5 text-[11px] text-[#c6cbd2] hover:bg-[rgb(255_255_255/0.08)] hover:text-white" onClick={cyclePlaybackRate} aria-label={t("monRate")}>
            {playbackRate}x
          </button>
        </div>
        <div className="timecode text-xs text-[#e8eaed]">
          {formatTimecode(playhead)}
          <span className="text-[#82878f]"> / {formatTimecode(totalDuration)}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className={showScopes ? "bg-[rgb(255_255_255/0.1)]! text-primary!" : undefined}
            onClick={() => setShowScopes((on) => !on)}
            aria-label={t("scopes")}
            title={t("scopes")}
          >
            <Activity size={14} />
          </Button>
          <Button variant="ghost" size="icon" onClick={toggleMuted} aria-label={t("monMute")}>
            {masterMuted || volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </Button>
          <Slider
            className="w-[68px] flex-none [--slider-range:rgba(255,255,255,0.75)] [--slider-thumb:#ffffff] [--slider-track:rgba(255,255,255,0.22)]"
            min={0}
            max={1}
            step={0.05}
            value={[masterMuted ? 0 : volume]}
            onValueChange={([value]) => setVolume(value)}
            aria-label={t("monVolume")}
          />
          <Button variant="ghost" size="icon" onClick={toggleFullscreen} aria-label={t("monFullscreen")}>
            <Maximize2 size={13} />
          </Button>
        </div>
      </div>
    </div>
  );
}
