import React from "react";

import { assetFileUrl } from "@/api/client";
import { useEditorStore } from "@/stores/editorStore";

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

export interface AudioSourceSpec {
  key: string; // clip id
  assetId: string;
  srcIn: number;
  srcOut: number;
  timelineStart: number;
  speed: number;
  gain: number;
  muted: boolean;
  trackMuted: boolean;
}

const TICK_MS = 40;
// Re-anchor when the store playhead diverges from the audio clock by more than this (a scrub).
const SEEK_EPSILON = 0.12;

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
    // Master-clock anchor: playhead = anchorPlayhead + (ctx.currentTime - anchorCtx) * rate.
    let anchorCtx = 0;
    let anchorPlayhead = 0;
    let hasSession = false;

    const clipEnd = (s: AudioSourceSpec) => s.timelineStart + Math.max(0, (s.srcOut - s.srcIn) / (s.speed || 1));
    // Effective linear gain: clip gain × master volume, zeroed by any mute.
    const gainValue = (s: AudioSourceSpec, volume: number, masterMuted: boolean) =>
      s.muted || s.trackMuted || masterMuted ? 0 : Math.min(1, Math.max(0, s.gain ?? 1)) * volume;

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
      gain.gain.value = gainValue(s, volume, masterMuted);
      node.connect(gain).connect(master);
      node.start(0, offset);
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
          existing.gain.gain.value = gainValue(s, volume, masterMuted);
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
        anchorCtx = ctx.currentTime;
        anchorPlayhead = state.playhead;
        hasSession = true;
        reconcile(state.playhead, rate, volume, masterMuted);
        return;
      }

      const expected = anchorPlayhead + (ctx.currentTime - anchorCtx) * rate;
      // A scrub (or clip edit) moved the playhead out from under us → re-anchor + reschedule.
      if (Math.abs(state.playhead - expected) > SEEK_EPSILON) {
        anchorCtx = ctx.currentTime;
        anchorPlayhead = state.playhead;
        stopAll();
        reconcile(state.playhead, rate, volume, masterMuted);
        return;
      }

      let next = expected;
      const total = totalRef.current;
      if (total > 0 && next >= total) {
        if (loop) {
          anchorCtx = ctx.currentTime;
          anchorPlayhead = 0;
          next = 0;
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
      reconcile(next, rate, volume, masterMuted);
    }, TICK_MS);

    return () => {
      window.clearInterval(interval);
      stopAll();
      void ctx.close();
    };
  }, []);

  return null;
}
