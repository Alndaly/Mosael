import { describe, expect, it } from "vitest";

import { jobDisplayStatus, runStatusLabelKey, runStatusText } from "./runStatus";

describe("任务状态的叫法", () => {
  it("认识的状态给对应的键", () => {
    expect(runStatusLabelKey("queued")).toBe("runStatus_queued");
    expect(runStatusLabelKey("cancelled")).toBe("runStatus_cancelled");
  });

  it("不认识的状态返回 null,显示时原样给状态值,不拼出一串不存在的键", () => {
    expect(runStatusLabelKey("paused")).toBeNull();
    // 原型链上的名字不算认识
    expect(runStatusLabelKey("toString")).toBeNull();
    const t = (key: string) => `«${key}»`;
    expect(runStatusText(t, "succeeded")).toBe("«runStatus_succeeded»");
    expect(runStatusText(t, "paused")).toBe("paused");
  });
});

describe("给界面看的那种状态", () => {
  it("被停下的(库里是 failed、cancelled 为真)按「已取消」说;真失败、别的状态原样", () => {
    expect(jobDisplayStatus({ status: "failed", cancelled: true })).toBe("cancelled");
    expect(jobDisplayStatus({ status: "failed", cancelled: false })).toBe("failed");
    expect(jobDisplayStatus({ status: "failed" })).toBe("failed");
    expect(jobDisplayStatus({ status: "succeeded", cancelled: true })).toBe("succeeded");
    expect(jobDisplayStatus({ status: "running" })).toBe("running");
  });
});
