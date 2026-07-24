import React from "react";

import { assetFileUrl, type Clip } from "@/api/client";
import { clipProgress, sampleGain, type GainKeyframe } from "@/features/editor/keyframes";

/**
 * One audio-track clip as its own self-syncing `<audio>`, so multiple audio tracks play at
 * once (the preview used a single shared element that only ever played the first audio track —
 * e.g. detached audio on A2 stayed silent). Applies the clip's gain/mute over the master volume;
 * seeks to the playhead like MonitorElement does for video.
 */
export function AudioElement({
  clip,
  playing,
  playhead,
  playbackRate,
  volume,
  masterMuted,
  trackMuted,
}: {
  clip: Clip;
  playing: boolean;
  playhead: number;
  playbackRate: number;
  volume: number;
  masterMuted: boolean;
  trackMuted: boolean;
}) {
  const ref = React.useRef<HTMLAudioElement | null>(null);
  const loadedRef = React.useRef<string | null>(null);

  React.useEffect(() => {
    const audio = ref.current;
    if (!audio || !clip.asset_id) return;
    if (loadedRef.current !== clip.asset_id) {
      loadedRef.current = clip.asset_id;
      audio.src = assetFileUrl(clip.asset_id);
    }
    const speed = clip.speed || 1;
    const desired = clip.src_in + (playhead - clip.timeline_start) * speed;
    if (Math.abs(audio.currentTime - desired) > 0.18) audio.currentTime = desired;
    audio.playbackRate = playbackRate * speed;
    // 音量关键帧:按播放头在片段内的进度采样增益,预览随之实时变化(与导出的 volume 表达式一致)。
    const gainKfs = (clip.effects as { gain_keyframes?: GainKeyframe[] } | undefined)?.gain_keyframes;
    const gain =
      Array.isArray(gainKfs) && gainKfs.length > 0
        ? sampleGain(gainKfs, clip.gain ?? 1, clipProgress(clip, playhead))
        : (clip.gain ?? 1);
    audio.volume = Math.min(1, Math.max(0, gain)) * (masterMuted ? 0 : volume);
    audio.muted = Boolean(clip.muted) || trackMuted;
    if (playing && audio.paused) audio.play().catch(() => undefined);
    else if (!playing && !audio.paused) audio.pause();
  }, [
    clip.asset_id, clip.src_in, clip.timeline_start, clip.speed, clip.gain, clip.muted, clip.effects,
    playing, playhead, playbackRate, volume, masterMuted, trackMuted,
  ]);

  React.useEffect(() => () => ref.current?.pause(), []);

  return <audio ref={ref} preload="auto" />;
}
