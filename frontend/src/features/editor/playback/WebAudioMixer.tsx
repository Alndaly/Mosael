import React from "react";

import { assetFileUrl } from "@/api/client";
import { audioGainAt, type AudioSourceSpec } from "./audioMix";
export type { AudioSourceSpec } from "./audioMix";
import { useEditorStore } from "@/features/editor/editorStore";
import { setPlaybackClock } from "./playbackClock";

/**
 * S3 of the compositor: all preview audio through one WebAudio graph, and the AudioContext
 * clock drives the playhead (the timeline's master clock while the compositor is active).
 *
 * Each active audio-bearing clip is an AudioBufferSourceNode → per-clip GainNode → master
 * GainNode → destination. Source nodes are one-shot, so we (re)schedule on play, seek and
 * when clips enter/leave. `ctx.currentTime` is the time base: each tick advances the store
 * playhead from it; if the playhead was moved externally (a scrub) we re-anchor and reschedule.
 *
 * Mounted only when the compositor is active; Monitor's interval clock stands down meanwhile.
 */

const TICK_MS = 40;
// The store playhead equals the value we last set unless someone else moved it; a divergence
// past this (a scrub / frame-step / clip edit) means a seek → reschedule from the new position.
const SEEK_EPSILON = 0.02;
// 插值时钟最多往两次节拍之间外推这么远:节拍被节流(后台标签页)时宁可停住,也不要一路冲过头。
const MAX_EXTRAPOLATE_SEC = 0.25;

export function WebAudioMixer({
  sources,
  totalDuration,
}: {
  sources: AudioSourceSpec[];
  totalDuration: number;
}) {
  const sourcesRef = React.useRef(sources);
  sourcesRef.current = sources;
  const totalRef = React.useRef(totalDuration);
  totalRef.current = totalDuration;

  React.useEffect(() => {
    const AudioCtx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const master = ctx.createGain();
    master.connect(ctx.destination);

    const buffers = new Map<string, AudioBuffer>(); // assetId → decoded
    const loading = new Set<string>();
    const active = new Map<string, { node: AudioBufferSourceNode; gain: GainNode }>();
    // Master clock, integrated incrementally: each tick advances the playhead by the real
    // AudioContext time elapsed since the last tick × the CURRENT rate (so a rate change is
    // absorbed per-interval, never mistaken for a seek, and a throttled background tick just
    // integrates a bigger dt correctly). An external seek is detected by comparing the store
    // playhead to the value we last set — anything else means someone else moved it.
    let lastCtx = 0;
    let lastSet = 0;
    let lastTickPerf = 0;
    let hasSession = false;
    // 插值时钟已经报出去的最大值:同一段播放里画面只往前走,节拍之间的抖动不会让它倒退一帧。
    let reported = 0;
    const anchor = (playhead: number) => {
      lastCtx = ctx.currentTime;
      lastSet = playhead;
      lastTickPerf = performance.now();
      reported = playhead;
    };

    // 「此刻」的上下文时间。优先用输出时间戳:它给出「正在从扬声器出来的那一刻」对应的上下文时间
    // 和 performance 时间,按 performance.now() 外推就是连续的,而且自动扣掉了输出延迟 —— 画面对的是
    // 听到的声音,不是刚排进去的声音。拿不到时退回「上一拍的上下文时间 + 墙钟流逝」。
    const contextNow = (): number => {
      const now = performance.now();
      const stamp = typeof ctx.getOutputTimestamp === "function" ? ctx.getOutputTimestamp() : null;
      if (stamp && typeof stamp.contextTime === "number" && typeof stamp.performanceTime === "number" && stamp.performanceTime > 0) {
        return stamp.contextTime + Math.max(0, now - stamp.performanceTime) / 1000;
      }
      return lastCtx + Math.max(0, now - lastTickPerf) / 1000;
    };
    setPlaybackClock(() => {
      const state = useEditorStore.getState();
      if (!hasSession) return state.playhead;
      const elapsed = Math.max(-MAX_EXTRAPOLATE_SEC, Math.min(MAX_EXTRAPOLATE_SEC, contextNow() - lastCtx));
      let value = Math.max(reported, lastSet + elapsed * state.playbackRate);
      const total = totalRef.current;
      if (total > 0) value = Math.min(value, total);
      reported = value;
      return value;
    });

    const clipEnd = (s: AudioSourceSpec) => s.timelineStart + Math.max(0, (s.srcOut - s.srcIn) / (s.speed || 1));
    // Effective linear gain: clip gain × master volume, zeroed by any mute. 音量关键帧存在时,
    // 按播放头在片段内的进度采样增益(与 AudioElement 和导出的 volume 表达式一致)。
    const gainValue = (s: AudioSourceSpec, volume: number, masterMuted: boolean, playhead: number) =>
      audioGainAt(s, sourcesRef.current, playhead, volume, masterMuted);

    const stopAll = () => {
      for (const { node } of active.values()) {
        try {
          node.stop();
        } catch {
          /* already stopped */
        }
      }
      active.clear();
    };

    const ensureBuffer = (assetId: string) => {
      if (buffers.has(assetId) || loading.has(assetId)) return;
      loading.add(assetId);
      fetch(assetFileUrl(assetId))
        .then((r) => r.arrayBuffer())
        .then((buf) => ctx.decodeAudioData(buf))
        .then((decoded) => {
          buffers.set(assetId, decoded);
        })
        .catch(() => undefined)
        .finally(() => loading.delete(assetId));
    };

    const scheduleClip = (s: AudioSourceSpec, playhead: number, rate: number, volume: number, masterMuted: boolean) => {
      const buffer = buffers.get(s.assetId);
      if (!buffer) {
        ensureBuffer(s.assetId);
        return;
      }
      const speed = s.speed || 1;
      const offset = s.srcIn + (playhead - s.timelineStart) * speed;
      if (offset < 0 || offset >= buffer.duration) return;
      const node = ctx.createBufferSource();
      node.buffer = buffer;
      node.playbackRate.value = rate * speed;
      const gain = ctx.createGain();
      gain.gain.value = gainValue(s, volume, masterMuted, playhead);
      node.connect(gain).connect(master);
      // Pass the clip's remaining buffer span as duration so the node self-terminates at its
      // trim-out (srcOut) even if the reconcile tick is throttled (backgrounded tab), instead
      // of bleeding past the cut until the next tick stops it.
      const remaining = Math.min(s.srcOut, buffer.duration) - offset;
      if (remaining <= 0) return;
      node.start(0, offset, remaining);
      active.set(s.key, { node, gain });
    };

    const reconcile = (playhead: number, rate: number, volume: number, masterMuted: boolean) => {
      master.gain.value = 1; // per-clip gains already fold in master volume; keep master unity
      const wanted = new Set<string>();
      for (const s of sourcesRef.current) {
        if (playhead < s.timelineStart || playhead >= clipEnd(s)) continue;
        wanted.add(s.key);
        const existing = active.get(s.key);
        if (existing) {
          existing.gain.gain.value = gainValue(s, volume, masterMuted, playhead);
          existing.node.playbackRate.value = rate * (s.speed || 1);
        } else {
          scheduleClip(s, playhead, rate, volume, masterMuted);
        }
      }
      for (const [key, { node }] of active) {
        if (!wanted.has(key)) {
          try {
            node.stop();
          } catch {
            /* ignore */
          }
          active.delete(key);
        }
      }
    };

    const interval = window.setInterval(() => {
      const state = useEditorStore.getState();
      const { playing, playbackRate: rate, volume, muted: masterMuted, loop } = state;

      if (!playing) {
        if (hasSession) {
          stopAll();
          hasSession = false;
        }
        return;
      }
      if (ctx.state === "suspended") void ctx.resume();

      if (!hasSession) {
        anchor(state.playhead);
        hasSession = true;
        reconcile(state.playhead, rate, volume, masterMuted);
        return;
      }

      // Someone else moved the playhead (scrub, clip edit) → adopt it and reschedule.
      if (Math.abs(state.playhead - lastSet) > SEEK_EPSILON) {
        anchor(state.playhead);
        stopAll();
        reconcile(state.playhead, rate, volume, masterMuted);
        return;
      }

      const dt = ctx.currentTime - lastCtx;
      lastCtx = ctx.currentTime;
      lastTickPerf = performance.now();
      let next = lastSet + dt * rate;
      const total = totalRef.current;
      if (total > 0 && next >= total) {
        if (loop) {
          next = 0;
          reported = 0; // 回到开头:插值时钟的「只进不退」从这里重新算
          stopAll();
        } else {
          state.setPlayhead(total);
          state.setPlaying(false);
          stopAll();
          hasSession = false;
          return;
        }
      }
      state.setPlayhead(next);
      lastSet = next;
      reconcile(next, rate, volume, masterMuted);
    }, TICK_MS);

    return () => {
      window.clearInterval(interval);
      setPlaybackClock(null);
      stopAll();
      void ctx.close();
    };
  }, []);

  return null;
}
