/**
 * 真正加载 wsolaWorklet.ts(AudioWorkletGlobalScope 的几个全局换成测试里的),像浏览器那样一块
 * 128 帧地调 process():起点之前是静音、2 倍速的 440Hz 放出来还是 440Hz、放完返回 false 让节点结束。
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const RATE = 48000;
type Processor = {
  port: { onmessage: ((event: { data: unknown }) => void) | null };
  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean;
};
let registered: { name: string; ctor: new (options: unknown) => Processor } | null = null;

beforeEach(() => {
  vi.resetModules();
  registered = null;
  vi.stubGlobal("sampleRate", RATE);
  vi.stubGlobal("currentFrame", 0);
  vi.stubGlobal(
    "AudioWorkletProcessor",
    class {
      port = { onmessage: null };
    },
  );
  vi.stubGlobal("registerProcessor", (name: string, ctor: new (options: unknown) => Processor) => {
    registered = { name, ctor };
  });
});
afterEach(() => vi.unstubAllGlobals());

it("起点之前静音;2 倍速的 440Hz 放出来还是 440Hz、时长减半;放完返回 false", async () => {
  await import("./wsolaWorklet");
  expect(registered?.name).toBe("mosael-wsola");
  const processor = new registered!.ctor({ processorOptions: { channels: 2, tempo: 2 } });
  const send = (data: unknown) => processor.port.onmessage?.({ data });

  const tone = new Float32Array(RATE);
  for (let i = 0; i < tone.length; i++) tone[i] = 0.5 * Math.sin((2 * Math.PI * 440 * i) / RATE);
  send({ type: "start", frame: 1000 });
  send({ type: "push", channels: [tone, tone] });
  send({ type: "end" });

  const out: number[] = [];
  let alive = true;
  for (let frame = 0; alive && frame < RATE * 2; frame += 128) {
    vi.stubGlobal("currentFrame", frame);
    const block = [new Float32Array(128), new Float32Array(128)];
    alive = processor.process([], [block]);
    out.push(...block[0]);
  }
  expect(alive).toBe(false);
  expect(out.slice(0, 1000).every((v) => v === 0)).toBe(true);
  const voiced = out.slice(1000);
  // 时长减半(容许几个步长的尾巴)。
  expect(voiced.length / RATE).toBeCloseTo(0.5, 1);
  let crossings = 0;
  const from = Math.floor(voiced.length * 0.1);
  const to = Math.floor(voiced.length * 0.9);
  for (let i = from + 1; i < to; i++) if (voiced[i - 1] < 0 && voiced[i] >= 0) crossings++;
  const frequency = crossings / ((to - from) / RATE);
  expect(frequency).toBeGreaterThan(440 * 0.97);
  expect(frequency).toBeLessThan(440 * 1.03);
});
