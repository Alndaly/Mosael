import { describe, expect, it } from "vitest";

import { originalFrame } from "./OriginalVideoSource";

function video(overrides: Partial<Parameters<typeof originalFrame>[0]> = {}) {
  return {
    readyState: 2,
    videoWidth: 3840,
    videoHeight: 2160,
    currentTime: 2,
    seeking: false,
    ...overrides,
  };
}

describe("originalFrame", () => {
  it("原片解出目标时刻时返回原生尺寸", () => {
    expect(originalFrame(video(), 2)).toEqual({ width: 3840, height: 2160 });
  });

  it("还在 seek 或尚未有帧时不返回,让调用方继续画代理", () => {
    expect(originalFrame(video({ readyState: 1 }), 2)).toBeNull();
    expect(originalFrame(video({ currentTime: 1.8 }), 2)).toBeNull();
  });

  it("容忍一帧以内的 seek 落点,避免 29.97fps 下无限重 seek", () => {
    expect(originalFrame(video({ currentTime: 1.99 }), 2)).toEqual({ width: 3840, height: 2160 });
  });
});
