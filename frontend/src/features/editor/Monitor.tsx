import React from "react";
import { Pause, Play, SkipBack } from "lucide-react";

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
export function Monitor({ sequence, assets }: { sequence: Sequence; assets: Asset[] }) {
  const t = useI18n();
  const playhead = useEditorStore((state) => state.playhead);
  const playing = useEditorStore((state) => state.playing);
  const { setPlayhead, setPlaying, togglePlaying } = useEditorStore.getState();
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const loadedAssetRef = React.useRef<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const loadedAudioAssetRef = React.useRef<string | null>(null);

  const assetById = React.useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const videoClips = React.useMemo(() => {
    const track = (sequence.tracks ?? []).find((item) => item.kind === "video");
    return [...(track?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start);
  }, [sequence]);
  const audioTrack = React.useMemo(
    () => (sequence.tracks ?? []).find((item) => item.kind === "audio") ?? null,
    [sequence],
  );
  const audioClips = React.useMemo(
    () => [...(audioTrack?.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start),
    [audioTrack],
  );
  const totalDuration = React.useMemo(
    () => sequenceDuration((sequence.tracks ?? []).flatMap((track) => track.clips ?? [])),
    [sequence],
  );

  const activeClip =
    videoClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;
  const activeAsset = activeClip ? (assetById.get(activeClip.asset_id) ?? null) : null;
  const isImage = activeAsset?.kind === "image";
  const activeAudioClip =
    audioClips.find((clip) => playhead >= clip.timeline_start && playhead < clipEnd(clip)) ?? null;

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
      const next = state.playhead + dt;
      if (totalDuration > 0 && next >= totalDuration) {
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
    const desired = playhead - activeClip.timeline_start + activeClip.src_in;
    if (Math.abs(video.currentTime - desired) > 0.18) {
      video.currentTime = desired;
    }
    if (playing && video.paused) {
      video.play().catch(() => undefined);
    } else if (!playing && !video.paused) {
      video.pause();
    }
  }, [playhead, playing, activeClip, activeAsset, isImage]);

  // Keep the audio-track element in lockstep as well.
  React.useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!activeAudioClip) {
      if (!audio.paused) audio.pause();
      return;
    }
    if (loadedAudioAssetRef.current !== activeAudioClip.asset_id) {
      loadedAudioAssetRef.current = activeAudioClip.asset_id;
      audio.src = assetFileUrl(activeAudioClip.asset_id);
    }
    const desired = playhead - activeAudioClip.timeline_start + activeAudioClip.src_in;
    if (Math.abs(audio.currentTime - desired) > 0.18) {
      audio.currentTime = desired;
    }
    audio.volume = Math.min(1, Math.max(0, activeAudioClip.gain));
    audio.muted = activeAudioClip.muted || Boolean(audioTrack?.muted);
    if (playing && audio.paused) {
      audio.play().catch(() => undefined);
    } else if (!playing && !audio.paused) {
      audio.pause();
    }
  }, [playhead, playing, activeAudioClip, audioTrack]);

  return (
    <div className="monitor-stack">
      <audio ref={audioRef} preload="auto" />
      <div className="monitor-stage">
        <video
          ref={videoRef}
          className="monitor-video"
          style={{ display: activeClip && !isImage ? "block" : "none" }}
          muted={false}
          playsInline
          preload="auto"
        />
        {activeClip && isImage && activeAsset && (
          <img className="monitor-video" src={assetFileUrl(activeAsset.id)} alt="" />
        )}
        {!activeClip && <div className="monitor-blank" />}
      </div>
      <div className="monitor-transport">
        <div className="monitor-buttons">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={() => setPlayhead(0)} aria-label="Go to start">
                <SkipBack size={15} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>00:00.0</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="secondary"
                size="icon-sm"
                onClick={() => {
                  if (!playing && totalDuration > 0 && playhead >= totalDuration) setPlayhead(0);
                  togglePlaying();
                }}
                aria-label={t("playPause")}
              >
                {playing ? <Pause size={15} /> : <Play size={15} />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("playPause")}</TooltipContent>
          </Tooltip>
        </div>
        <div className="monitor-timecode timecode">
          {formatTimecode(playhead)}
          <span className="monitor-total"> / {formatTimecode(totalDuration)}</span>
        </div>
      </div>
    </div>
  );
}
