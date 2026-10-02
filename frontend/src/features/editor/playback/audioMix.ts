import type { Asset, Track } from "@/api/client";
import { sampleGain, type GainKeyframe } from "@/features/editor/keyframes";

export interface AudioSourceSpec {
  key: string;
  assetId: string;
  /**
   * 这一段该从哪份音频代理里取声音:素材 id + 代理指纹。代理还没好(转码中)、没有音轨(silent)、
   * 转坏了都是 null —— 混音器不去取它,这一段先不出声;代理好了指纹一变,自然接上。
   */
  audioProxy: string | null;
  srcIn: number;
  srcOut: number;
  timelineStart: number;
  speed: number;
  gain: number;
  gainKeyframes?: GainKeyframe[];
  muted: boolean;
  trackMuted: boolean;
  soloMuted?: boolean;
  duck?: boolean;
  fadeIn?: number;
  fadeOut?: number;
}
const duration = (s: AudioSourceSpec) => Math.max(0, (s.srcOut - s.srcIn) / (s.speed || 1));
const silent = (s: AudioSourceSpec) => s.muted || s.trackMuted || s.soloMuted;
const clamp = (x: number, max: number) => Math.max(0, Math.min(max, Number.isFinite(x) ? x : 0));

/** 素材的音频代理指纹;没有可用的代理时为 null。 */
export function audioProxyKey(asset: Asset | undefined): string | null {
  const info = (asset?.media_info ?? {}) as { audio_proxy_status?: string; audio_proxy_key?: string };
  return asset && info.audio_proxy_status === "ready" && info.audio_proxy_key ? `${asset.id}:${info.audio_proxy_key}` : null;
}

/** 音频代理还在转的素材(转好之前预览里这一段没有声音,界面要去拉新状态)。 */
export function audioProxyPending(asset: Asset | undefined): boolean {
  return (asset?.media_info as { audio_proxy_status?: string } | undefined)?.audio_proxy_status === "pending";
}

export function buildAudioSources(tracks: Track[], assets: Map<string, Asset>): AudioSourceSpec[] {
  const soloActive = tracks.some(t => t.solo);
  return tracks.filter(t => t.kind === "video" || t.kind === "audio").flatMap(track =>
    (track.clips ?? []).filter(c => c.asset_id && (track.kind === "audio" || assets.get(c.asset_id)?.kind === "video")).map(c => {
      const effects = c.effects as { gain_keyframes?: GainKeyframe[]; fade_in?: number; fade_out?: number } | undefined;
      return {
        key: c.id, assetId: c.asset_id!, audioProxy: audioProxyKey(assets.get(c.asset_id!)),
        srcIn: c.src_in, srcOut: c.src_out,
        timelineStart: c.timeline_start, speed: c.speed || 1, gain: c.gain ?? 1,
        gainKeyframes: effects?.gain_keyframes, fadeIn: effects?.fade_in, fadeOut: effects?.fade_out,
        muted: Boolean(c.muted), trackMuted: Boolean(track.muted), soloMuted: soloActive && !track.solo,
        duck: Boolean(track.duck),
      };
    }),
  );
}

/**
 * Mirrors render_plan's fades/solo/duck windows and render_executor's linear gain.
 *
 * 闪避:标了闪避的轨,在**任何**一条没标闪避、此刻有声的轨同时发声时压到 0.3。基底视频轨两头都算 ——
 * 它的声音会让音乐轨让路(人声在原片里、音乐在音频轨上,最常见的就是这个形状),它自己标了闪避
 * 也会给配音让路(译配)。此前这里把基底轨两头都排除了,而导出那边已经会压基底轨:预览和成片不一样。
 */
export function audioGainAt(s: AudioSourceSpec, sources: AudioSourceSpec[], time: number, volume = 1, masterMuted = false): number {
  const dur = duration(s), local = time - s.timelineStart;
  if (masterMuted || silent(s) || local < 0 || local >= dur) return 0;
  const points = (s.gainKeyframes ?? []).filter(k => Number.isFinite(k.t) && Number.isFinite(k.gain))
    .map(k => ({ t: clamp(k.t, 1), gain: clamp(k.gain, 4) }));
  // Export treats a single point as static clip gain.
  let gain = points.length >= 2 ? sampleGain(points, s.gain, local / dur) : s.gain;
  let fi = Math.max(0, Number(s.fadeIn) || 0), fo = Math.max(0, Number(s.fadeOut) || 0);
  if (fi + fo > dur) { const ratio = dur / (fi + fo); fi *= ratio; fo *= ratio; }
  fi = Math.round(fi * 1e6) / 1e6; fo = Math.round(fo * 1e6) / 1e6;
  gain = clamp(gain, 4) * (fi > 0 ? Math.min(1, local / fi) : 1) * (fo > 0 ? Math.min(1, (dur - local) / fo) : 1);
  if (s.duck && sources.some(other => {
    if (other.key === s.key || other.duck || silent(other)) return false;
    const start = Math.max(s.timelineStart, other.timelineStart);
    const end = Math.min(s.timelineStart + dur, other.timelineStart + duration(other));
    return end - start > 0.01 && time >= start && time <= end;
  })) gain *= 0.3;
  return gain * clamp(volume, 1);
}
