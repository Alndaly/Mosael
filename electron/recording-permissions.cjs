const MACOS_PRIVACY_PANES = Object.freeze({
  camera: "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
  microphone: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
  // macOS 15+ presents this pane as “Screen & System Audio Recording”. The stable
  // Privacy_ScreenCapture deep link remains the route used to open it.
  screen: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
});

const WINDOWS_PRIVACY_PANES = Object.freeze({
  camera: "ms-settings:privacy-webcam",
  microphone: "ms-settings:privacy-microphone",
});

const PERMISSION_KINDS = new Set(["camera", "microphone", "screen"]);
const REQUESTABLE_PERMISSION_KINDS = new Set(["camera", "microphone"]);

function assertPermissionKind(kind, allowedKinds = PERMISSION_KINDS) {
  if (!allowedKinds.has(kind)) throw new TypeError(`Unsupported recording permission: ${String(kind)}`);
}

/**
 * Keep operating-system permission policy in the main process. The renderer owns the
 * recording flow, but it should not know platform-specific System Settings URLs or call
 * Electron APIs directly.
 */
function createRecordingPermissionService({ platform, shell, systemPreferences }) {
  return {
    getStatus(kind) {
      assertPermissionKind(kind);
      if (platform !== "darwin") return "unknown";
      return systemPreferences.getMediaAccessStatus(kind);
    },

    async request(kind) {
      assertPermissionKind(kind, REQUESTABLE_PERMISSION_KINDS);
      // Electron only exposes an explicit native request for camera and microphone on
      // macOS. Screen/system-audio consent is requested by getDisplayMedia's system picker.
      if (platform !== "darwin") return null;
      return systemPreferences.askForMediaAccess(kind);
    },

    /**
     * 屏幕录制**没有**可以主动请求的原生授权接口(`askForMediaAccess` 只认摄像头/麦克风):
     * macOS 只在应用**真的尝试抓屏**时才把这个应用登记进「屏幕与系统音频录制」列表并弹授权框。
     * 所以这里主动问一次 `desktopCapturer.getSources` —— 它的副作用正是那次登记。
     *
     * 为什么需要它:开发者实测(2026-10-23)在本地开发版里点「开始录制」,出来的是 Chromium 那个
     * 只列窗口的选择器(「Share This Window / Share All Electron Windows」)—— 因为系统权限没授予,
     * macOS 不让列出整块屏幕。而这个应用在授权列表里**根本还没出现**,用户没地方可开。
     */
    async prepareScreen(desktopCapturer) {
      if (platform !== "darwin") return { status: "unknown", screens: 0 };
      const status = systemPreferences.getMediaAccessStatus("screen");
      let screens = 0;
      try {
        const sources = await desktopCapturer.getSources({
          types: ["screen"],
          thumbnailSize: { width: 1, height: 1 },
        });
        screens = sources.length;
      } catch {
        /* 拿不到源 = 还没授权;状态照样交回去,界面按它说话 */
      }
      return { status, screens };
    },

    async openSettings(kind) {
      assertPermissionKind(kind);
      const url =
        platform === "darwin"
          ? MACOS_PRIVACY_PANES[kind]
          : platform === "win32"
            ? WINDOWS_PRIVACY_PANES[kind]
            : undefined;
      if (!url) return false;
      await shell.openExternal(url);
      return true;
    },
  };
}

module.exports = { createRecordingPermissionService };
