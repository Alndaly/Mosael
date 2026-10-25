import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { DesktopDriverMac } from "./desktopDriverMac.cjs";

function harness() {
  const calls: Array<[string, string[]]> = [];
  const runner = vi.fn(async (file: string, args: string[]) => {
    calls.push([file, args]);
    if (file === "screencapture") {
      fs.writeFileSync(args[2], Buffer.from("fake-png"));
      return { stdout: "", stderr: "" };
    }
    if (file === "sips") {
      return { stdout: "pixelWidth: 800\npixelHeight: 600\n", stderr: "" };
    }
    const kind = args[0];
    if (kind === "windows") {
      return { stdout: JSON.stringify([{ id: 7, owner: "Finder", title: "Documents", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]), stderr: "" };
    }
    if (kind === "ax") {
      return { stdout: JSON.stringify({ snapshot_id: "snap-1", elements: [{ id: "snap-1:0", role: "AXButton", title: "Save" }] }), stderr: "" };
    }
    throw new Error(`unexpected ${file} ${kind}`);
  });
  return { calls, runner };
}

describe("DesktopDriverMac(ADR 0081 P1)", () => {
  it("capabilities 是只读:有树与截图,没有输入", () => {
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool" });
    expect(driver.capabilities()).toEqual({ tree: true, screenshots: true, input: false, platforms: ["macos-window"] });
  });

  it("windows 枚举在屏窗口(CDWindowList 的字段原样交回)", async () => {
    const { runner, calls } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const windows = await driver.windows();
    expect(windows).toHaveLength(1);
    expect(windows[0]).toMatchObject({ id: 7, owner: "Finder", width: 800, height: 600, onscreen: true, active: true });
    expect(calls[0]).toEqual(["/fake/tool", ["windows"]]);
  });

  it("observe(windowNumber) 用 screencapture 拍一张并给出尺寸", async () => {
    const { runner } = harness();
    const file = "/tmp/mosael-test-window.png";
    fs.writeFileSync(file, Buffer.from("fake-png"));
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const shot = await driver.observe({ windowNumber: 7 });
    expect(shot.width).toBe(800);
    expect(shot.height).toBe(600);
    expect(shot.image).toBe(Buffer.from("fake-png").toString("base64"));
    expect(shot.elements).toEqual([]);
    expect(shot.meta).toEqual({ windowNumber: 7 });
  });

  it("observe(pid) 返回一次性 snapshot_id 与元素令牌", async () => {
    const { runner } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const result = await driver.observe({ pid: 42 });
    expect(result.meta).toEqual({ pid: 42, snapshot_id: "snap-1" });
    expect(result.elements).toEqual([{ id: "snap-1:0", role: "AXButton", title: "Save" }]);
  });

  it("act 与 verify 都不支持,明确报出来", async () => {
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool" });
    await expect(driver.act({ kind: "click" })).rejects.toThrow("act_not_supported");
    expect(driver.verify()).toEqual({ ok: false, reason: "verify_not_supported", evidence: null });
  });

  it("工具回错时把原文带出来,不静默降级", async () => {
    const driver = new DesktopDriverMac({
      binaryPath: "/fake/tool",
      runner: async () => { throw new Error("screen recording permission required"); },
    });
    await expect(driver.observe({ windowNumber: 7 })).rejects.toThrow("screen recording permission required");
  });
});
