import { describe, expect, it } from "vitest";

import { selectPrimaryVideo } from "../src/platforms/video-element";

function candidate(overrides: Partial<{
  currentSrc: string;
  src: string;
  duration: number;
  readyState: number;
  paused: boolean;
  area: number;
}> = {}) {
  const value = {
    currentSrc: "",
    src: "",
    duration: Number.NaN,
    readyState: 0,
    paused: true,
    area: 0,
    ...overrides,
  };
  return {
    ...value,
    getBoundingClientRect: () => ({ width: Math.sqrt(value.area), height: Math.sqrt(value.area) }),
  };
}

describe("selectPrimaryVideo", () => {
  it("ignores empty placeholder videos before the active Pornhub player", () => {
    const placeholder = candidate();
    const active = candidate({
      currentSrc: "blob:https://www.pornhub.com/video",
      duration: 514.8,
      readyState: 4,
      paused: false,
      area: 640 * 360,
    });

    expect(selectPrimaryVideo([placeholder, placeholder, active])).toBe(active);
  });

  it("prefers the visible main player over a hidden playing ad", () => {
    const hiddenAd = candidate({ currentSrc: "blob:ad", duration: 20, readyState: 4, paused: false });
    const visiblePlayer = candidate({
      currentSrc: "blob:video",
      duration: 600,
      readyState: 4,
      paused: true,
      area: 640 * 360,
    });

    expect(selectPrimaryVideo([hiddenAd, visiblePlayer])).toBe(visiblePlayer);
  });
});
