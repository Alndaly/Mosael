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

  it("变速片段按 速率 × 速度 推进(本条提交里先用 playbackRate)", () => {
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
