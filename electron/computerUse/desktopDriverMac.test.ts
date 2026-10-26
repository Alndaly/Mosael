import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { DesktopDriverMac } from "./desktopDriverMac.cjs";

function harness() {
  const calls: Array<[string, string[]]> = [];
  const performInputs: Array<Record<string, unknown>> = [];
  const runner = vi.fn(async (file: string, args: string[], _timeout?: number, input?: string) => {
    calls.push([file, args]);
    if (file === "screencapture") {
      fs.writeFileSync(args[2], Buffer.from("fake-png"));
      return { stdout: "", stderr: "" };
    }
    if (file === "sips") {
      return { stdout: "pixelWidth: 800\npixelHeight: 600\n", stderr: "" };
    }
    const kind = args[0];
    if (kind === "permissions") {
      return { stdout: JSON.stringify({ accessibility: true, screen: true }), stderr: "" };
    }
    if (kind === "request-permission") {
      return { stdout: JSON.stringify({ granted: true }), stderr: "" };
    }
    if (kind === "windows") {
      return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Finder", title: "Documents", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]), stderr: "" };
    }
    if (kind === "ax") {
      return { stdout: JSON.stringify({ snapshot_id: "snap-1", elements: [{ id: "snap-1:0", path: "0.1", role: "AXButton", title: "Save", frame: { x: 10, y: 20, width: 100, height: 40 } }] }), stderr: "" };
    }
    if (kind === "perform") {
      const request = JSON.parse(String(input)) as Record<string, unknown>;
      performInputs.push(request);
      return { stdout: JSON.stringify({ ok: true, action: request.action, point: request.point }), stderr: "" };
    }
    throw new Error(`unexpected ${file} ${kind}`);
  });
  return { calls, performInputs, runner };
}

describe("DesktopDriverMac(ADR 0081)", () => {
  it("capabilities 有树、截图与动作", () => {
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool" });
    expect(driver.capabilities()).toEqual({ tree: true, screenshots: true, input: true, platforms: ["macos-window"] });
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
    expect(shot.meta).toMatchObject({ windowNumber: 7, capture_id: expect.any(String) });
  });

  it("observe(pid) 返回一次性 snapshot_id 与元素令牌", async () => {
    const { runner } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const result = await driver.observe({ pid: 42 });
    expect(result.meta).toEqual({ pid: 42, snapshot_id: "snap-1" });
    expect(result.elements).toEqual([
      { id: "snap-1:0", path: "0.1", role: "AXButton", title: "Save", frame: { x: 10, y: 20, width: 100, height: 40 } },
    ]);
  });

  it("受保护应用的截图与 AX 都拒绝,而且不先申请权限", async () => {
    const calls: string[] = [];
    const runner = vi.fn(async (file: string, args: string[]) => {
      if (args[0] === "permissions") {
        calls.push("permissions");
        return { stdout: JSON.stringify({ accessibility: true, screen: true }), stderr: "" };
      }
      if (file === "/fake/tool" && args[0] === "windows") {
        calls.push("windows");
        return {
          stdout: JSON.stringify([{ id: 7, pid: 42, owner: "1Password", title: "Vault", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]),
          stderr: "",
        };
      }
      if (file === "screencapture" || (file === "/fake/tool" && args[0] === "ax")) {
        calls.push(file === "screencapture" ? "screencapture" : "ax");
        return { stdout: "", stderr: "" };
      }
      throw new Error(`unexpected ${file} ${args[0]}`);
    });
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });

    await expect(driver.observe({ windowNumber: 7 })).rejects.toMatchObject({ code: "desktop_protected_app" });
    await expect(driver.observe({ pid: 42 })).rejects.toMatchObject({ code: "desktop_protected_app" });
    expect(calls).not.toContain("permissions");
    expect(calls).not.toContain("screencapture");
    expect(calls).not.toContain("ax");
  });

  it("verify 仍不支持,不冒充已验证", () => {
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool" });
    expect(driver.verify()).toEqual({ ok: false, reason: "verify_not_supported", evidence: null });
  });

  it("令牌动作重读 AX 后点元素中心", async () => {
    const { runner, performInputs } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await driver.observe({ pid: 42 });
    const result = await driver.act({ kind: "click", token: "snap-1:0", button: "left", clickCount: 2 });
    expect(result).toMatchObject({ kind: "click", windowNumber: 7, pid: 42, point: { x: 60, y: 40 } });
    expect(performInputs).toEqual([{
      action: "click",
      pid: 42,
      point: { x: 60, y: 40 },
      button: "left",
      clickCount: 2,
      text: "",
      dy: 0,
    }]);
  });

  it("像素动作把截图坐标映射到窗口全局坐标", async () => {
    const { runner, performInputs } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const shot = await driver.observe({ windowNumber: 7 });
    await driver.act({ kind: "click", captureId: shot.meta.capture_id, x: 400, y: 300 });
    expect(performInputs[0]).toMatchObject({ action: "click", pid: 42, point: { x: 401, y: 302 } });
  });

  it("令牌对应的界面变了就拒绝,不点旧坐标", async () => {
    const { runner } = harness();
    const original = runner.getMockImplementation()!;
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await driver.observe({ pid: 42 });
    runner.mockImplementation(async (file, args, timeout, input) => {
      if (file === "/fake/tool" && args[0] === "ax") {
        return { stdout: JSON.stringify({ snapshot_id: "snap-1", elements: [{ id: "snap-1:0", path: "0.1", role: "AXButton", title: "Delete", frame: { x: 10, y: 20, width: 100, height: 40 } }] }), stderr: "" };
      }
      return original(file, args, timeout, input);
    });
    await expect(driver.act({ kind: "click", token: "snap-1:0" })).rejects.toMatchObject({ code: "desktop_stale_snapshot" });
  });

  it("回放请求会在动作前后各拍一张缩小证据", async () => {
    const { runner, performInputs } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await driver.observe({ pid: 42 });
    const result = await driver.act({ kind: "type", token: "snap-1:0", text: "hello", replay: true });
    expect(performInputs[0]).toMatchObject({ action: "type", text: "hello" });
    expect(result.replay.action).toMatchObject({ kind: "type", text: "hello" });
    expect(result.replay.before).toMatchObject({ width: 800, height: 600 });
    expect(result.replay.after).toMatchObject({ width: 800, height: 600 });
  });


  it("绑定只允许用一次", async () => {
    const { runner } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await driver.observe({ pid: 42 });
    await driver.act({ kind: "click", token: "snap-1:0" });
    await expect(driver.act({ kind: "click", token: "snap-1:0" }))
      .rejects.toMatchObject({ code: "desktop_stale_snapshot" });
  });


  it("受保护应用直接拒绝,不落到 CGEvent", async () => {
    const { runner, performInputs } = harness();
    const original = runner.getMockImplementation()!;
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await driver.observe({ pid: 42 });
    runner.mockImplementation(async (file, args, timeout, input) => {
      if (file === "/fake/tool" && args[0] === "windows") {
        return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Terminal", title: "zsh", x: 1, y: 2, width: 800, height: 600, onscreen: true }]), stderr: "" };
      }
      return original(file, args, timeout, input);
    });
    await expect(driver.act({ kind: "click", token: "snap-1:0" })).rejects.toMatchObject({ code: "desktop_protected_app" });
    expect(performInputs).toEqual([]);
  });

  it("截图后窗口移动就拒绝,不点漂移的坐标", async () => {
    const { runner } = harness();
    const original = runner.getMockImplementation()!;
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    const shot = await driver.observe({ windowNumber: 7 });
    runner.mockImplementation(async (file, args, timeout, input) => {
      if (file === "/fake/tool" && args[0] === "windows") {
        return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Finder", title: "Documents", x: 50, y: 2, width: 800, height: 600, onscreen: true }]), stderr: "" };
      }
      return original(file, args, timeout, input);
    });
    await expect(driver.act({ kind: "click", captureId: shot.meta.capture_id, x: 10, y: 10 }))
      .rejects.toMatchObject({ code: "desktop_stale_capture" });
  });


  it("工具回错时把原文带出来,不静默降级", async () => {
    const driver = new DesktopDriverMac({
      binaryPath: "/fake/tool",
      runner: async () => { throw new Error("screen recording permission required"); },
    });
    await expect(driver.observe({ windowNumber: 7 })).rejects.toThrow("screen recording permission required");
  });

  it("权限状态查询不申请权限,也不弹引导", async () => {
    const { runner, calls } = harness();
    const permissionGuide = vi.fn();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner, permissionGuide });
    await expect(driver.permissions()).resolves.toEqual({ accessibility: true, screen: true });
    expect(permissionGuide).not.toHaveBeenCalled();
    expect(calls).toEqual([["/fake/tool", ["permissions"]]]);
  });

  it("缺权限时先给用户引导,仍未授权则报结构化错误", async () => {
    const runner = vi.fn(async (_binary: string, args: string[]) => {
      if (args[0] === "windows") {
        return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Finder", title: "Documents", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]), stderr: "" };
      }
      return { stdout: JSON.stringify({ accessibility: false, screen: false }), stderr: "" };
    });
    const permissionGuide = vi.fn().mockResolvedValue({ action: "settings", opened: true });
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner, permissionGuide });
    const failure = await driver.observe({ pid: 42 }).catch((error) => error);
    expect(permissionGuide).toHaveBeenCalledWith("accessibility");
    expect(failure).toMatchObject({ code: "desktop_permission_required", permission: "accessibility" });
    expect(runner).toHaveBeenCalledTimes(3); // windows + permissions ×2
  });

  it("用户在引导里授权后,同一次观察继续执行", async () => {
    let granted = false;
    const runner = vi.fn(async (_binary: string, args: string[]) => {
      if (args[0] === "permissions") {
        return { stdout: JSON.stringify({ accessibility: granted, screen: true }), stderr: "" };
      }
      if (args[0] === "windows") {
        return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Finder", title: "Documents", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]), stderr: "" };
      }
      return { stdout: JSON.stringify({ snapshot_id: "snap-2", elements: [] }), stderr: "" };
    });
    const permissionGuide = vi.fn(async () => { granted = true; });
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner, permissionGuide });
    await expect(driver.observe({ pid: 42 })).resolves.toMatchObject({ meta: { snapshot_id: "snap-2" } });
    expect(permissionGuide).toHaveBeenCalledWith("accessibility");
  });

  it("只有显式 requestPermission 才触发系统申请", async () => {
    const { runner, calls } = harness();
    const driver = new DesktopDriverMac({ binaryPath: "/fake/tool", runner });
    await expect(driver.requestPermission("screen")).resolves.toBe(true);
    expect(calls).toEqual([["/fake/tool", ["request-permission", "screen"]]]);
    await expect(driver.requestPermission("camera")).rejects.toThrow("Unsupported desktop permission");
  });
});
