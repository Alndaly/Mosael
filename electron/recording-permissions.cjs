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
