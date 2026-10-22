import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: Electron loads this module directly from main.cjs.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRecordingPermissionService } = require("./recording-permissions.cjs") as {
  createRecordingPermissionService: (dependencies: {
    platform: NodeJS.Platform;
    shell: { openExternal: (url: string) => Promise<void> };
    systemPreferences: {
      askForMediaAccess: (kind: "camera" | "microphone") => Promise<boolean>;
      getMediaAccessStatus: (kind: "camera" | "microphone" | "screen") => string;
    };
  }) => {
    getStatus: (kind: "camera" | "microphone" | "screen") => string;
    request: (kind: "camera" | "microphone") => Promise<boolean | null>;
    openSettings: (kind: "camera" | "microphone" | "screen") => Promise<boolean>;
    prepareScreen: (desktopCapturer: {
      getSources: (options: { types: string[]; thumbnailSize: { width: number; height: number } }) => Promise<unknown[]>;
  }) => Promise<{ status: string; screens: number; prompted: boolean }>;
  };
};

describe("recording permission service", () => {
  it("uses the native macOS prompts for camera and microphone", async () => {
    const askForMediaAccess = vi.fn().mockResolvedValue(true);
    const service = createRecordingPermissionService({
      platform: "darwin",
      shell: { openExternal: vi.fn() },
      systemPreferences: { askForMediaAccess, getMediaAccessStatus: vi.fn(() => "not-determined") },
    });

    await expect(service.request("camera")).resolves.toBe(true);
    await expect(service.request("microphone")).resolves.toBe(true);
    expect(askForMediaAccess.mock.calls).toEqual([["camera"], ["microphone"]]);
  });

  it("opens the combined screen and system audio privacy pane on macOS", async () => {
    const openExternal = vi.fn().mockResolvedValue(undefined);
    const service = createRecordingPermissionService({
      platform: "darwin",
      shell: { openExternal },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus: vi.fn(() => "denied") },
    });

    await expect(service.openSettings("screen")).resolves.toBe(true);
    expect(openExternal).toHaveBeenCalledWith(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    );
  });

  it("lets the renderer fall back to getUserMedia where native prompts are unavailable", async () => {
    const service = createRecordingPermissionService({
      platform: "linux",
      shell: { openExternal: vi.fn() },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus: vi.fn(() => "unknown") },
    });

    await expect(service.request("camera")).resolves.toBeNull();
    expect(service.getStatus("screen")).toBe("unknown");
    await expect(service.openSettings("screen")).resolves.toBe(false);
  });
});

describe("screen recording needs an actual capture attempt", () => {
  it("asks desktopCapturer for screens — that call is what registers the app in the system list", async () => {
    const getSources = vi.fn().mockResolvedValue([{ id: "screen:0:0" }, { id: "screen:1:0" }]);
    const getMediaAccessStatus = vi.fn(() => "not-determined");
    const service = createRecordingPermissionService({
      platform: "darwin",
      shell: { openExternal: vi.fn() },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus },
    });

    await expect(service.prepareScreen({ getSources })).resolves.toMatchObject({ status: "not-determined", screens: 2 });
    //: 只问「屏幕」:窗口那张缩略图对授权没有帮助,却会把所有窗口都枚举一遍。
    expect(getSources.mock.calls[0][0]).toMatchObject({ types: ["screen"] });
  });

  it("a failing or empty enumeration still reports the status instead of throwing", async () => {
    const service = createRecordingPermissionService({
      platform: "darwin",
      shell: { openExternal: vi.fn() },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus: vi.fn(() => "denied") },
    });

    const openSettings = vi.fn().mockResolvedValue(true);
    const denied = createRecordingPermissionService({
      platform: "darwin",
      shell: { openExternal: openSettings },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus: vi.fn(() => "denied") },
    });
    const result = await denied.prepareScreen({ getSources: vi.fn().mockRejectedValue(new Error("nope")) });
    expect(result).toMatchObject({ status: "denied", screens: 0, prompted: false });
    //: 已经拒绝过就不会再弹框:要顺手把设置面板打开,而不是让人对着不动的界面等。
    expect(openSettings).toHaveBeenCalled();
  });

  it("on other platforms there is nothing to register", async () => {
    const getSources = vi.fn();
    const service = createRecordingPermissionService({
      platform: "win32",
      shell: { openExternal: vi.fn() },
      systemPreferences: { askForMediaAccess: vi.fn(), getMediaAccessStatus: vi.fn(() => "unknown") },
    });
    await expect(service.prepareScreen({ getSources })).resolves.toEqual({
      status: "unknown",
      screens: 0,
      prompted: false,
    });
    expect(getSources).not.toHaveBeenCalled();
  });
});
