const { DesktopDriverMac } = require("./desktopDriverMac.cjs");

const DESKTOP_PERMISSION_PANES = Object.freeze({
  accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
  screen: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
});

/**
 * Computer Use 桌面权限的原生引导(ADR 0081)。
 *
 * 只负责解释与分流:首次申请走 macOS 授权框;此前拒绝过则让用户自己去系统设置打开。
 * 查询权限、弹出这个对话框本身都不会申请权限;只有用户点了对应按钮才执行动作。
 */
function createDesktopPermissionGuide({ platform, dialog, shell, requestPermission, t }) {
  return {
    async show(kind) {
      if (!Object.prototype.hasOwnProperty.call(DESKTOP_PERMISSION_PANES, kind)) {
        throw new TypeError(`Unsupported desktop permission: ${String(kind)}`);
      }
      if (platform !== "darwin") return { supported: false, action: "unsupported" };

      const { response } = await dialog.showMessageBox({
        type: "info",
        title: t("desktopPermission_title"),
        message: kind === "accessibility" ? t("desktopPermission_accessibilityMessage") : t("desktopPermission_screenMessage"),
        detail: t("desktopPermission_detail"),
        buttons: [t("desktopPermission_request"), t("desktopPermission_openSettings"), t("common_cancel")],
        defaultId: 0,
        cancelId: 2,
        noLink: true,
      });
      if (response === 0) {
        return { supported: true, action: "request", granted: await requestPermission(kind) };
      }
      if (response === 1) {
        await shell.openExternal(DESKTOP_PERMISSION_PANES[kind]);
        return { supported: true, action: "settings", opened: true };
      }
      return { supported: true, action: "cancel" };
    },
  };
}

/** 正式装配入口:主进程只需给 Electron 的 dialog / shell 与主进程文案函数。 */
function createGuidedDesktopDriverMac({ platform = process.platform, dialog, shell, t, ...driverOptions }) {
  const driver = new DesktopDriverMac(driverOptions);
  const guide = createDesktopPermissionGuide({
    platform,
    dialog,
    shell,
    t,
    requestPermission: (kind) => driver.requestPermission(kind),
  });
  driver.permissionGuide = (kind) => guide.show(kind);
  return driver;
}

module.exports = { createDesktopPermissionGuide, createGuidedDesktopDriverMac, DESKTOP_PERMISSION_PANES };
