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
