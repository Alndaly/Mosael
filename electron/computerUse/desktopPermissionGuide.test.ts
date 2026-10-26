import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: the Electron main process loads this module directly.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createDesktopPermissionGuide, createGuidedDesktopDriverMac } = require("./desktopPermissionGuide.cjs");

function harness(response = 2, platform: NodeJS.Platform = "darwin") {
  const dialog = { showMessageBox: vi.fn().mockResolvedValue({ response }) };
  const shell = { openExternal: vi.fn().mockResolvedValue(undefined) };
  const requestPermission = vi.fn().mockResolvedValue(true);
  const guide = createDesktopPermissionGuide({
    platform,
    dialog,
    shell,
    requestPermission,
    t: (key: string) => key,
  });
  return { dialog, shell, requestPermission, guide };
}

describe("desktop permission guide(ADR 0081)", () => {
  it("只有点「向系统申请」才触发 macOS 授权框", async () => {
    const { guide, dialog, shell, requestPermission } = harness(0);
    await expect(guide.show("accessibility")).resolves.toEqual({ supported: true, action: "request", granted: true });
    expect(requestPermission).toHaveBeenCalledWith("accessibility");
    expect(shell.openExternal).not.toHaveBeenCalled();
    expect(dialog.showMessageBox).toHaveBeenCalledWith(expect.objectContaining({
      title: "desktopPermission_title",
      message: "desktopPermission_accessibilityMessage",
      buttons: ["desktopPermission_request", "desktopPermission_openSettings", "common_cancel"],
      defaultId: 0,
      cancelId: 2,
    }));
  });

  it("点「打开系统设置」只打开对应隐私面板", async () => {
    const { guide, shell, requestPermission } = harness(1);
    await expect(guide.show("screen")).resolves.toEqual({ supported: true, action: "settings", opened: true });
    expect(shell.openExternal).toHaveBeenCalledWith(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    );
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("取消不申请、不打开设置", async () => {
    const { guide, shell, requestPermission } = harness(2);
    await expect(guide.show("accessibility")).resolves.toEqual({ supported: true, action: "cancel" });
    expect(shell.openExternal).not.toHaveBeenCalled();
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("非 macOS 不伪装成有这套 TCC 引导", async () => {
    const { guide, dialog } = harness(0, "win32");
    await expect(guide.show("screen")).resolves.toEqual({ supported: false, action: "unsupported" });
    expect(dialog.showMessageBox).not.toHaveBeenCalled();
  });
  it("正式装配把原生引导、系统申请和驱动重试连成一条路", async () => {
    let granted = false;
    const runner = vi.fn(async (_binary: string, args: string[]) => {
      if (args[0] === "permissions") {
        return { stdout: JSON.stringify({ accessibility: granted, screen: true }), stderr: "" };
      }
      if (args[0] === "request-permission") {
        granted = true;
        return { stdout: JSON.stringify({ granted: true }), stderr: "" };
      }
      if (args[0] === "windows") {
        return { stdout: JSON.stringify([{ id: 7, pid: 42, owner: "Finder", title: "Documents", x: 1, y: 2, width: 800, height: 600, layer: 0, alpha: 1, onscreen: true, active: true }]), stderr: "" };
      }
      return { stdout: JSON.stringify({ snapshot_id: "snap-guided", elements: [] }), stderr: "" };
    });
    const { dialog, shell } = harness(0);
    const driver = createGuidedDesktopDriverMac({
      platform: "darwin",
      dialog,
      shell,
      t: (key: string) => key,
      binaryPath: "/fake/tool",
      runner,
    });
    await expect(driver.observe({ pid: 42 })).resolves.toMatchObject({ meta: { snapshot_id: "snap-guided" } });
    expect(dialog.showMessageBox).toHaveBeenCalledOnce();
    expect(runner.mock.calls.map((call) => call[1][0])).toEqual([
      "windows", "permissions", "request-permission", "permissions", "ax",
    ]);
  });

});
