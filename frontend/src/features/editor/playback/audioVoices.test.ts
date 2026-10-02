/**
 * 预览混音的声部:按块从音频代理取 PCM,首尾相接地排进上下文时间轴。
 *
 * 解码源换成「块随叫随到 / 永远解不出 / 读不出」的假对象(真实的取数与解码见 audioProxySource.test),
 * AudioContext 换成记账的假对象 —— 这里钉的是**排程**:何时开、从哪开、接缝对不对、坏的不重试、
 * 用不到的块放掉。
 */
import { describe, expect, it, vi } from "vitest";

import type { AudioSourceSpec } from "./audioMix";
import { AUDIO_CHUNK_SEC, type AudioProxySource, type PcmChunk } from "./audioProxySource";
import { AudioVoices } from "./audioVoices";
import type { StretchNode } from "./stretchWorklet";

interface Started {
  when: number;
  offset: number;
  duration: number;
  rate: number;
}

class FakeContext {
  started: Started[] = [];
  gains: { gain: { value: number } }[] = [];
  createGain() {
    const gain = { gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() };
    this.gains.push(gain);
    return gain as unknown as GainNode;
  }
  createBuffer(channels: number, frames: number, sampleRate: number) {
    return { numberOfChannels: channels, length: frames, sampleRate, copyToChannel: vi.fn() } as unknown as AudioBuffer;
  }
  createBufferSource() {
    const node = {
      buffer: null as AudioBuffer | null,
      playbackRate: { value: 1 },
      onended: null,
      connect: vi.fn(),
      stop: vi.fn(),
      start: (when: number, offset: number, duration: number) => this.started.push({ when, offset, duration, rate: node.playbackRate.value }),
    };
    return node as unknown as AudioBufferSourceNode;
  }
}

/** 一份 60 秒的代理;`decoded` 里列着的块号「已经解好」。 */
class FakeSource {
  ok = true;
  duration = 60;
  requested: number[] = [];
  retained: { keep: number[]; spare: number }[] = [];
  closed = false;
  constructor(public decoded: Set<number> | "all" = "all") {}
  chunk(k: number): PcmChunk | null {
    if (this.decoded !== "all" && !this.decoded.has(k)) return null;
    const frames = AUDIO_CHUNK_SEC * 48000;
    return { index: k, start: k * AUDIO_CHUNK_SEC, sampleRate: 48000, channels: [new Float32Array(frames), new Float32Array(frames)], frames };
  }
  request(k: number) {
    this.requested.push(k);
  }
  retain(keep: ReadonlySet<number>, spare: number) {
    this.retained.push({ keep: [...keep].sort((a, b) => a - b), spare });
  }
  close() {
    this.closed = true;
  }
}

const spec = (over: Partial<AudioSourceSpec> = {}): AudioSourceSpec => ({
  key: "c1", assetId: "a1", audioProxy: "a1:proxy", srcIn: 0, srcOut: 20, timelineStart: 0, speed: 1,
  gain: 1, muted: false, trackMuted: false, ...over,
});
const state = (playhead: number, rate = 1) => ({ playhead, rate, volume: 1, muted: false });

function setup(source: FakeSource = new FakeSource()) {
  const ctx = new FakeContext();
  const made: string[] = [];
  const voices = new AudioVoices(ctx as unknown as BaseAudioContext, {} as AudioNode, (assetId) => {
    made.push(assetId);
    return source as unknown as AudioProxySource;
  });
  return { ctx, voices, made, source };
}

describe("排程", () => {
  it("片段增益送进 WebAudio 图(放大也照送)", () => {
    const { ctx, voices } = setup();
    voices.play([spec({ gain: 3 })], 10, state(1));
    expect(ctx.gains.at(-1)!.gain.value).toBe(3);
  });

  it("从播放头所在的块、块内偏移处开播;下一块首尾相接地排在后面", () => {
    const { ctx, voices } = setup();
    // 播放头 3.8s:第 0 块还剩 0.2s,前瞻 0.5s 够排到第 1 块。
    voices.play([spec()], 100, state(3.8));
    expect(ctx.started).toHaveLength(2);
    const [first, second] = ctx.started;
    expect(first.when).toBeCloseTo(100, 9);
    expect(first.offset).toBeCloseTo(3.8, 9);
    expect(first.duration).toBeCloseTo(0.2, 9);
    // 接缝:第二块的起点 = 第一块的终点,从块头开始。
    expect(second.when).toBeCloseTo(first.when + first.duration, 9);
    expect(second.offset).toBe(0);
  });

  it("只请求眼前和前面几秒的块,不解整份", () => {
    const { voices, source } = setup();
    voices.play([spec({ srcOut: 60 })], 0, state(10));
    expect(Math.min(...source.requested)).toBe(Math.floor(10 / AUDIO_CHUNK_SEC));
    expect(Math.max(...source.requested)).toBeLessThanOrEqual(Math.floor(20 / AUDIO_CHUNK_SEC));
  });

  it("前瞻窗口里还没开始的片段:按精确的上下文时间从入点开,而不是等播放头跨进去的那一拍", () => {
    const { ctx, voices } = setup();
    voices.play([spec({ timelineStart: 5.3, srcIn: 2 })], 50, state(5));
    expect(ctx.started[0].when).toBeCloseTo(50.3, 9);
    expect(ctx.started[0].offset).toBeCloseTo(2, 9);
  });

  it("片段在出点停:最后一段的时长截在 srcOut", () => {
    const { ctx, voices } = setup();
    voices.play([spec({ srcOut: 4.1 })], 0, state(3.9));
    expect(ctx.started.map((s) => s.duration).reduce((a, b) => a + b, 0)).toBeCloseTo(0.2, 9);
  });

  it("块还没解出来:先不排;解出来时已经晚了,从「此刻」该播的位置接上,不从块头补放", () => {
    const source = new FakeSource(new Set());
    const { ctx, voices } = setup(source);
    voices.play([spec()], 0, state(1));
    expect(ctx.started).toHaveLength(0);
    source.decoded = new Set([0]);
    // 0.3s 后的下一拍:播放头 1.3s。
    voices.play([spec()], 0.3, state(1.3));
    expect(ctx.started[0].when).toBeCloseTo(0.3, 9);
    expect(ctx.started[0].offset).toBeCloseTo(1.3, 9);
  });

  it("加载不了变速 worklet 时:变速片段退回 playbackRate,按 速率 × 速度 推进", () => {
    const { ctx, voices } = setup();
    voices.play([spec({ speed: 2, srcOut: 40 })], 0, state(1));
    expect(ctx.started[0].rate).toBe(2);
    expect(ctx.started[0].offset).toBeCloseTo(2, 9);
  });
});

describe("代理不在 / 坏了", () => {
  it("代理还没好(audioProxy 为空):不去取", () => {
    const { voices, made } = setup();
    voices.play([spec({ audioProxy: null })], 0, state(1));
    expect(made).toHaveLength(0);
  });

  it("读不出 / 解不了的代理:记住它,之后每拍都不再新建、不再请求(此前每 40ms 整份重下一遍)", () => {
    const source = new FakeSource();
    source.ok = false;
    const { voices, made, ctx } = setup(source);
    for (let tick = 0; tick < 50; tick++) voices.play([spec()], tick * 0.04, state(1 + tick * 0.04));
    expect(made).toHaveLength(1);
    expect(source.requested).toHaveLength(0);
    expect(ctx.started).toHaveLength(0);
  });
});

describe("内存", () => {
  it("暂停时:只留播放头下那一块(外加备用),用不到的放掉", () => {
    const { voices, source } = setup();
    voices.idle([spec()], 9);
    expect(source.requested).toEqual([2]);
    const last = source.retained.at(-1)!;
    expect(last.keep).toContain(2);
    expect(last.keep.every((k) => k >= 2 && k <= Math.floor((9 + 8) / AUDIO_CHUNK_SEC))).toBe(true);
  });

  it("时间线上不再用的代理:解码源连同块一起关掉", () => {
    const { voices, source } = setup();
    voices.play([spec()], 0, state(1));
    voices.play([], 0.04, state(1.04));
    expect(source.closed).toBe(true);
  });
});

describe("变速不变调(worklet 声部)", () => {
  class FakeStretchNode {
    messages: { type: string; frame?: number; channels?: Float32Array[] }[] = [];
    connect = vi.fn();
    disconnect = vi.fn();
    port = { postMessage: (message: { type: string }) => this.messages.push(message) };
    constructor(readonly tempo: number) {}
    pushedSeconds() {
      return this.messages.filter((m) => m.type === "push").reduce((sum, m) => sum + m.channels![0].length, 0) / 48000;
    }
  }
  function setupStretch(source = new FakeSource()) {
    const parts = setup(source);
    (parts.ctx as unknown as { sampleRate: number }).sampleRate = 48000;
    const nodes: FakeStretchNode[] = [];
    parts.voices.enableStretch((tempo) => {
      const node = new FakeStretchNode(tempo);
      nodes.push(node);
      return node as unknown as StretchNode;
    });
    return { ...parts, nodes };
  }

  it("2 倍速片段:不调 playbackRate,建一个 tempo=2 的 worklet 节点,按上下文帧号起声,块按顺序推进去", () => {
    const { ctx, voices, nodes } = setupStretch();
    voices.play([spec({ speed: 2, srcOut: 40 })], 10, state(1));
    expect(ctx.started).toHaveLength(0);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].tempo).toBe(2);
    expect(nodes[0].messages[0]).toEqual({ type: "start", frame: 10 * 48000 });
    // 从媒体 2s(播放头 1s × 速度 2)推起,推到上下文 now + 0.5s 以后的那一块为止。
    expect(nodes[0].pushedSeconds()).toBeCloseTo(AUDIO_CHUNK_SEC - 2, 6);
  });

  it("推到出点就说一声 end;seek / 删片段时 stop", () => {
    const { voices, nodes } = setupStretch();
    voices.play([spec({ speed: 1.5, srcOut: 3 })], 0, state(0));
    expect(nodes[0].messages.at(-1)!.type).toBe("end");
    voices.stopAll();
    expect(nodes[0].messages.at(-1)!.type).toBe("stop");
    expect(nodes[0].disconnect).toHaveBeenCalled();
  });

  it("中途某块到点还没解出来:推等长的静音占住时间,后面的声音不会比画面晚", () => {
    const source = new FakeSource(new Set([0]));
    const { voices, nodes } = setupStretch(source);
    voices.play([spec({ speed: 2, srcOut: 40 })], 0, state(0));
    expect(nodes[0].pushedSeconds()).toBeCloseTo(AUDIO_CHUNK_SEC, 6);
    // 第 1 块(媒体 4–8s)本该在上下文 2s 开始;到 2.1s 还没解出来。
    voices.play([spec({ speed: 2, srcOut: 40 })], 2.1, state(2.1));
    const silent = nodes[0].messages.filter((m) => m.type === "push").at(-1)!;
    expect(silent.channels![0].length).toBe(AUDIO_CHUNK_SEC * 48000);
    expect(silent.channels![0].every((v) => v === 0)).toBe(true);
  });
});
