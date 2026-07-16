import React from "react";
import { Maximize2, Pause, Play, Repeat, SkipBack, SkipForward, StepBack, StepForward, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl, type Asset, type Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { clipEnd, formatTimecode, sequenceDuration } from "@/domain/timeline/geometry";
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

export function Monitor({ sequence, assets }: { sequence: Sequence; assets: Asset[] }) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const playing = useEditorStore((state) => state.playing);
  const loop = useEditorStore((state) => state.loop);
  const playbackRate = useEditorStore((state) => state.playbackRate);
  const volume = useEditorStore((state) => state.volume);
  const masterMuted = useEditorStore((state) => state.muted);
  const { setPlayhead, setPlaying, togglePlaying, toggleLoop, cyclePlaybackRate, setVolume, toggleMuted } =
    useEditorStore.getState();
  const stageRef = React.useRef<HTMLDivElement | null>(null);
  const scrubRef = React.useRef<HTMLDivElement | null>(null);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const loadedAssetRef = React.useRef<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const loadedAudioAssetRef = React.useRef<string | null>(null);

  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const videoTracks = React.useMemo(
    () =>
      (sequence.tracks ?? [])
        .filter((item) => item.kind === "video")
        .sort((a, b) => a.position - b.position),
    [sequence],
  );
  const videoClips = React.useMemo(
    () => [...(videoTracks[0]?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start),
    [videoTracks],
  );
  const overlayClips = React.useMemo(
    () =>
      videoTracks
        .slice(1)
        .flatMap((track) => track.clips ?? [])
        .sort((a, b) => a.timeline_start - b.timeline_start),
    [videoTracks],
  );
  const audioTrack = React.useMemo(
    () => (sequence.tracks ?? []).find((item) => item.kind === "audio") ?? null,
    [sequence],
  );
  const audioClips = React.useMemo(
    () => [...(audioTrack?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start),
    [audioTrack],
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
  const activeSubtitle =
    subtitleClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeEffects = (activeClip?.effects ?? {}) as {
    filter?: string;
    color?: Record<string, number>;
  };
  const { cssFilter, vignette } = React.useMemo(() => {
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
    return { cssFilter: parts.join(" "), vignette: Math.max(0, v("vignette")) };
  }, [activeEffects.filter, activeEffects.color]);
  const isImage = activeAsset?.kind === "image";
  const activeAudioClip =
    audioClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeOverlayClip =
    overlayClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const overlayAsset = activeOverlayClip?.asset_id ? (assetById.get(activeOverlayClip.asset_id) ?? null) : null;
  const pip = {
    x: 0.62,
    y: 0.06,
    scale: 0.33,
    ...(((activeOverlayClip?.effects as { pip?: { x?: number; y?: number; scale?: number } })?.pip) ?? {}),
  };
  const overlayRef = React.useRef<HTMLVideoElement | null>(null);
  const loadedOverlayAssetRef = React.useRef<string | null>(null);

  // Overlay video (PiP) kept in lockstep, muted — export mixes only base+audio tracks.
  React.useEffect(() => {
    const video = overlayRef.current;
    if (!video) return;
    if (!activeOverlayClip || !overlayAsset || overlayAsset.kind === "image") {
      if (!video.paused) video.pause();
      return;
    }
    if (loadedOverlayAssetRef.current !== overlayAsset.id) {
      loadedOverlayAssetRef.current = overlayAsset.id;
      video.src = assetFileUrl(overlayAsset.id);
    }
    const desired =
      activeOverlayClip.src_in + (playhead - activeOverlayClip.timeline_start) * (activeOverlayClip.speed || 1);
    if (Math.abs(video.currentTime - desired) > 0.18) video.currentTime = desired;
    if (playing && video.paused) video.play().catch(() => undefined);
    else if (!playing && !video.paused) video.pause();
  }, [playhead, playing, activeOverlayClip, overlayAsset]);

  // Playback clock. Interval-based (not rAF) so it keeps running when the
  // window is occluded or backgrounded — audio keeps playing there too.
  React.useEffect(() => {
    if (!playing) return;
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
  }, [playing, totalDuration]);

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
    video.volume = masterMuted ? 0 : volume;
    if (playing && video.paused) {
      video.play().catch(() => undefined);
    } else if (!playing && !video.paused) {
      video.pause();
    }
  }, [playhead, playing, activeClip, activeAsset, isImage, playbackRate, volume, masterMuted]);

  // Keep the audio-track element in lockstep as well.
  React.useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!activeAudioClip) {
      if (!audio.paused) audio.pause();
      return;
    }
    if (activeAudioClip.asset_id && loadedAudioAssetRef.current !== activeAudioClip.asset_id) {
      loadedAudioAssetRef.current = activeAudioClip.asset_id;
      audio.src = assetFileUrl(activeAudioClip.asset_id);
    }
    const audioSpeed = activeAudioClip.speed || 1;
    const desired = activeAudioClip.src_in + (playhead - activeAudioClip.timeline_start) * audioSpeed;
    if (Math.abs(audio.currentTime - desired) > 0.18) {
      audio.currentTime = desired;
    }
    audio.playbackRate = playbackRate * audioSpeed;
    audio.volume = Math.min(1, Math.max(0, activeAudioClip.gain)) * (masterMuted ? 0 : volume);
    audio.muted = activeAudioClip.muted || Boolean(audioTrack?.muted);
    if (playing && audio.paused) {
      audio.play().catch(() => undefined);
    } else if (!playing && !audio.paused) {
      audio.pause();
    }
  }, [playhead, playing, activeAudioClip, audioTrack, playbackRate, volume, masterMuted]);

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
    const stage = stageRef.current;
    if (!stage) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void stage.requestFullscreen().catch(() => undefined);
  };
  const playToggle = () => {
    if (!playing && totalDuration > 0 && playhead >= totalDuration) setPlayhead(0);
    togglePlaying();
  };

  return (
    <div className="monitor-stack">
      <audio ref={audioRef} preload="auto" />
      <div className="monitor-stage">
        <div className="monitor-frame-wrap" ref={stageRef} onClick={playToggle}>
          <video
            ref={videoRef}
            className="monitor-video"
            style={{ display: activeClip && !isImage ? "block" : "none", filter: cssFilter || undefined }}
            muted={false}
            playsInline
            preload="auto"
          />
          {activeClip && isImage && activeAsset && (
            <img
              className="monitor-video"
              src={assetFileUrl(activeAsset.id)}
              alt=""
              style={{ filter: cssFilter || undefined }}
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
            <div className="monitor-subtitle">{activeSubtitle.text_override}</div>
          )}
          {activeOverlayClip && overlayAsset && (
            overlayAsset.kind === "image" ? (
              <img
                className="monitor-overlay"
                src={assetFileUrl(overlayAsset.id)}
                alt=""
                style={{ left: `${pip.x * 100}%`, top: `${pip.y * 100}%`, width: `${pip.scale * 100}%` }}
              />
            ) : (
              <video
                ref={overlayRef}
                className="monitor-overlay"
                style={{ left: `${pip.x * 100}%`, top: `${pip.y * 100}%`, width: `${pip.scale * 100}%` }}
                muted
                playsInline
                preload="auto"
              />
            )
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
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(0)} aria-label="start">
            <SkipBack size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(Math.max(0, playhead - frameStep))} aria-label="frame back">
            <StepBack size={14} />
          </Button>
          <Button variant="secondary" size="icon-sm" className="monitor-play" onClick={playToggle} aria-label={t("playPause")}>
            {playing ? <Pause size={14} /> : <Play size={14} className="monitor-play-icon" />}
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(Math.min(totalDuration, playhead + frameStep))} aria-label="frame forward">
            <StepForward size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(totalDuration)} aria-label="end">
            <SkipForward size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className={loop ? "monitor-active" : undefined}
            onClick={toggleLoop}
            aria-label="loop"
          >
            <Repeat size={13} />
          </Button>
          <button type="button" className="monitor-rate timecode" onClick={cyclePlaybackRate} aria-label="rate">
            {playbackRate}x
          </button>
        </div>
        <div className="monitor-timecode timecode">
          {formatTimecode(playhead)}
          <span className="monitor-total"> / {formatTimecode(totalDuration)}</span>
        </div>
        <div className="monitor-buttons">
          <Button variant="ghost" size="icon-sm" onClick={toggleMuted} aria-label="mute">
            {masterMuted || volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </Button>
          <input
            type="range"
            className="monitor-volume"
            min={0}
            max={1}
            step={0.05}
            value={masterMuted ? 0 : volume}
            onChange={(event) => setVolume(Number(event.target.value))}
            aria-label="volume"
          />
          <Button variant="ghost" size="icon-sm" onClick={toggleFullscreen} aria-label="fullscreen">
            <Maximize2 size={13} />
          </Button>
        </div>
      </div>
    </div>
  );
}
