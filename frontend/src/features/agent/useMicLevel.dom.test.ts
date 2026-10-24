/** @vitest-environment jsdom */
/**
 * 实时输入电平(说话输入那颗按钮上的三格)。
 *
 * 两条不变量:算得出来(有声音时 > 0、静音时 0),以及**没有 AudioContext 时不能炸** ——
 * 电平条是锦上添花,不该因为它让录音这条路挂掉(jsdom 里默认就没有 AudioContext)。
 */

import { describe, expect, it } from "vitest";

import { levelFromSamples } from "@/features/agent/useMicLevel";

const silent = (size = 512) => new Float32Array(size);
const tone = (amplitude: number, size = 512) => Float32Array.from({ length: size }, (_, i) => amplitude * Math.sin(i));

describe("levelFromSamples", () => {
  it("全零 → 0", () => {
    expect(levelFromSamples(silent())).toBe(0);
  });

  it("很小的声音 → 低电平,但不为 0", () => {
    const level = levelFromSamples(tone(0.01));
    expect(level).toBeGreaterThan(0);
    expect(level).toBeLessThan(0.4);
  });

  it("正常说话的音量 → 中高电平", () => {
    const level = levelFromSamples(tone(0.2));
    expect(level).toBeGreaterThan(0.4);
    expect(level).toBeLessThanOrEqual(1);
  });

  it("贴满的音量 → 接近封顶(正弦的 RMS 是 0.707,不会真到 1,也不会越界)", () => {
    const level = levelFromSamples(tone(1));
    expect(level).toBeGreaterThan(0.9);
    expect(level).toBeLessThanOrEqual(1);
  });
});
