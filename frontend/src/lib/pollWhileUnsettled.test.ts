import { describe, expect, it } from "vitest";

import { pollWhileUnsettled } from "./pollWhileUnsettled";

describe("要不要接着问", () => {
  it("下载中:问得勤一点", () => {
    expect(pollWhileUnsettled([{ status: "downloading", runtime_checked: true }])).toBe(1200);
  });

  it("探测还没答完:也要接着问 —— 否则「正在检查」会一直挂着", () => {
    expect(pollWhileUnsettled([{ status: "installed", runtime_checked: false }])).toBe(800);
  });

  it("都定了:停 —— 一个没人看的轮询只是噪声", () => {
    expect(pollWhileUnsettled([{ status: "installed", runtime_checked: true }])).toBe(false);
  });

  it("空列表(还没拉到)不轮询", () => {
    expect(pollWhileUnsettled([])).toBe(false);
    expect(pollWhileUnsettled(undefined)).toBe(false);
  });

  it("老后端没有这个字段时不该被当成「没答完」", () => {
    expect(pollWhileUnsettled([{ status: "installed" }])).toBe(false);
  });
});
