/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readSceneSnap, writeSceneSnap } from "./sceneSnap";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("吸附偏好", () => {
  it("没存过时是关的", () => {
    expect(readSceneSnap()).toBe(false);
  });

  it("存下之后读得回来", () => {
    writeSceneSnap(true);
    expect(readSceneSnap()).toBe(true);
    writeSceneSnap(false);
    expect(readSceneSnap()).toBe(false);
  });

  it("原样回传,好让调用点一句话完成翻转", () => {
    expect(writeSceneSnap(true)).toBe(true);
    expect(writeSceneSnap(false)).toBe(false);
  });

  it("存不进去也不抛 —— 这一次照常生效,只是下次不记得", () => {
    // 隐私窗口、站点数据被禁时 localStorage 的访问器本身就会抛。
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceeded");
    });
    expect(writeSceneSnap(true)).toBe(true);
  });

  it("读不出来时退回关闭,不让整页崩在一个偏好上", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readSceneSnap()).toBe(false);
  });
});
