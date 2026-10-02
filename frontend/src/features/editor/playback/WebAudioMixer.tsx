import React from "react";

import { type AudioSourceSpec } from "./audioMix";
export type { AudioSourceSpec } from "./audioMix";
import { AudioVoices } from "./audioVoices";
import { useEditorStore } from "@/features/editor/editorStore";
import { setPlaybackClock } from "./playbackClock";
import { loadStretchFactory } from "./stretchWorklet";

/**
 * S3 of the compositor: all preview audio through one WebAudio graph, and the AudioContext
 * clock drives the playhead (the timeline's master clock while the compositor is active).
 *
 * 每个有声片段从它素材的**音频代理**里按块取 PCM(见 audioVoices / audioProxySource),不再整份下载
 * 原文件、整份解码。`ctx.currentTime` is the time base: each tick advances the store playhead from it;
 * if the playhead was moved externally (a scrub) we re-anchor and reschedule. 画面要的连续时间由
 * playbackClock 按同一个时钟插值。
 */

const TICK_MS = 40;
// The store playhead equals the value we last set unless someone else moved it; a divergence
// past this (a scrub / frame-step / clip edit) means a seek → reschedule from the new position.
const SEEK_EPSILON = 0.02;
// 插值时钟最多往两次节拍之间外推这么远:节拍被节流(后台标签页)时宁可停住,也不要一路冲过头。
const MAX_EXTRAPOLATE_SEC = 0.25;
/**
 * 上下文固定跑在 48kHz:和音频代理同一个采样率,解出来的块直接用,不用逐块重采样(设备不是 48k 时由
 * 浏览器在输出端统一转一次)。
 */
const CONTEXT_SAMPLE_RATE = 48_000;

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
    const ctx = new AudioCtx({ sampleRate: CONTEXT_SAMPLE_RATE });
    const master = ctx.createGain();
    master.connect(ctx.destination);
    const voices = new AudioVoices(ctx, master);
    // 变速不变调的 worklet 异步加载;加载好之前(或加载不了)变速片段先用 playbackRate。
    let disposed = false;
    void loadStretchFactory(ctx).then((factory) => {
      if (factory && !disposed) voices.enableStretch(factory);
    });

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

    const interval = window.setInterval(() => {
      const state = useEditorStore.getState();
      const { playing, playbackRate: rate, volume, muted, loop } = state;
      const mix = (playhead: number) => ({ playhead, rate, volume, muted });

      if (!playing) {
        hasSession = false;
        // 暂停:声部全停,播放头下的那几块先解好(按下播放就有声音);用不到的块放掉。
        voices.idle(sourcesRef.current, state.playhead);
        return;
      }
      if (ctx.state === "suspended") void ctx.resume();

      if (!hasSession) {
        anchor(state.playhead);
        hasSession = true;
        voices.play(sourcesRef.current, ctx.currentTime, mix(state.playhead));
        return;
      }

      // Someone else moved the playhead (scrub, clip edit) → adopt it and reschedule.
      if (Math.abs(state.playhead - lastSet) > SEEK_EPSILON) {
        anchor(state.playhead);
        voices.stopAll();
        voices.play(sourcesRef.current, ctx.currentTime, mix(state.playhead));
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
          voices.stopAll();
        } else {
          state.setPlayhead(total);
          state.setPlaying(false);
          voices.stopAll();
          hasSession = false;
          return;
        }
      }
      state.setPlayhead(next);
      lastSet = next;
      voices.play(sourcesRef.current, ctx.currentTime, mix(next));
    }, TICK_MS);

    return () => {
      disposed = true;
      window.clearInterval(interval);
      setPlaybackClock(null);
      voices.close();
      void ctx.close();
    };
  }, []);

  return null;
}
