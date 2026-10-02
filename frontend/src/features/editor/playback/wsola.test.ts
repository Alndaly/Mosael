/**
 * 变速不变调:2 倍速的 440Hz 还是 440Hz,只是短了一半;0.5 倍速同理长一倍。
 *
 * 此前预览靠 playbackRate 变速,2 倍速的 440Hz 会变成 880Hz(花栗鼠),而导出的 atempo 不变调 ——
 * 预览和成片对不上。
 */
import { describe, expect, it } from "vitest";

import { WsolaStretcher } from "./wsola";

const RATE = 48000;

function sine(seconds: number, frequency: number, amplitude = 0.5): Float32Array {
  const out = new Float32Array(Math.round(seconds * RATE));
  for (let i = 0; i < out.length; i++) out[i] = amplitude * Math.sin((2 * Math.PI * frequency * i) / RATE);
  return out;
}

/** 一次喂完、按 128 帧一块拉(和 AudioWorklet 一样),拉到放完为止。 */
function stretch(input: Float32Array, tempo: number, pushSize = input.length): Float32Array {
  const stretcher = new WsolaStretcher(2, RATE);
  stretcher.tempo = tempo;
  const chunks: Float32Array[] = [];
  const block = [new Float32Array(128), new Float32Array(128)];
  for (let at = 0; at < input.length; at += pushSize) {
    const piece = input.subarray(at, Math.min(input.length, at + pushSize));
    stretcher.push([piece, piece]);
    for (let n = stretcher.pull(block, 128); n > 0; n = stretcher.pull(block, 128)) chunks.push(block[0].slice(0, n));
  }
  stretcher.end();
  for (let n = stretcher.pull(block, 128); n > 0; n = stretcher.pull(block, 128)) chunks.push(block[0].slice(0, n));
  const out = new Float32Array(chunks.reduce((sum, c) => sum + c.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/** 中段(去掉头尾各 10%)的过零次数换算出的频率。 */
function frequencyOf(signal: Float32Array): number {
  const from = Math.floor(signal.length * 0.1);
  const to = Math.floor(signal.length * 0.9);
  let crossings = 0;
  for (let i = from + 1; i < to; i++) if (signal[i - 1] < 0 && signal[i] >= 0) crossings++;
  return crossings / ((to - from) / RATE);
}

function rms(signal: Float32Array): number {
  const from = Math.floor(signal.length * 0.1);
  const to = Math.floor(signal.length * 0.9);
  let sum = 0;
  for (let i = from; i < to; i++) sum += signal[i] * signal[i];
  return Math.sqrt(sum / (to - from));
}

describe("WSOLA 变速不变调", () => {
  it("2 倍速:时长减半,音高不变(还是 440Hz,不是 880Hz)", () => {
    const out = stretch(sine(2, 440), 2);
    expect(out.length / RATE).toBeCloseTo(1, 1);
    expect(frequencyOf(out)).toBeGreaterThan(440 * 0.97);
    expect(frequencyOf(out)).toBeLessThan(440 * 1.03);
  });

  it("0.5 倍速:时长翻倍,音高不变", () => {
    const out = stretch(sine(1, 440), 0.5);
    expect(out.length / RATE).toBeCloseTo(2, 1);
    expect(frequencyOf(out)).toBeGreaterThan(440 * 0.97);
    expect(frequencyOf(out)).toBeLessThan(440 * 1.03);
  });

  it("1.5 倍速的人声基频(220Hz):音高不变,电平不起伏(重叠窗加起来是 1)", () => {
    const input = sine(2, 220, 0.5);
    const out = stretch(input, 1.5);
    expect(frequencyOf(out)).toBeGreaterThan(220 * 0.97);
    expect(frequencyOf(out)).toBeLessThan(220 * 1.03);
    expect(rms(out)).toBeGreaterThan(rms(input) * 0.9);
    expect(rms(out)).toBeLessThan(rms(input) * 1.1);
  });

  it("流式:一小块一小块地喂(AudioWorklet 里就是这样),结果和一次喂完一样", () => {
    const input = sine(1, 330);
    const whole = stretch(input, 1.25);
    const streamed = stretch(input, 1.25, 4096);
    expect(streamed.length).toBe(whole.length);
    let maxDiff = 0;
    for (let i = 0; i < whole.length; i++) maxDiff = Math.max(maxDiff, Math.abs(whole[i] - streamed[i]));
    expect(maxDiff).toBeLessThan(1e-6);
  });
});
