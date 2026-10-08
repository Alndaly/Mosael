import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
const { installPermissionPolicy, permissionAllowed } = createRequire(import.meta.url)("./web-permissions.cjs") as {
  permissionAllowed: (request: { trusted: boolean; permission: string; externalURL?: string }) => boolean;
  installPermissionPolicy: (target: FakeSession, options: { isAppUrl: ((url: string) => boolean) | null; log?: (line: string) => void }) => void;
};

type RequestHandler = (contents: unknown, permission: string, callback: (granted: boolean) => void, details?: Record<string, unknown>) => void;
type CheckHandler = (contents: unknown, permission: string, origin: string, details?: Record<string, unknown>) => boolean;
type FakeSession = {
  setPermissionRequestHandler: (handler: RequestHandler) => void;
  setPermissionCheckHandler: (handler: CheckHandler) => void;
  setDevicePermissionHandler: (handler: () => boolean) => void;
  request?: RequestHandler;
  check?: CheckHandler;
  device?: () => boolean;
};

function fakeSession(): FakeSession {
  const target: FakeSession = {
    setPermissionRequestHandler: (handler) => (target.request = handler),
    setPermissionCheckHandler: (handler) => (target.check = handler),
    setDevicePermissionHandler: (handler) => (target.device = handler),
  };
  return target;
}

/** 走一次请求处理器,回给没给。 */
function ask(target: FakeSession, permission: string, details: Record<string, unknown>, contents: unknown = null): boolean {
  let granted: boolean | undefined;
  target.request!(contents, permission, (value) => (granted = value), details);
  if (granted === undefined) throw new Error("the handler never answered");
  return granted;
}

const APP = "http://127.0.0.1:5173";
const isAppUrl = (url: string) => url.startsWith(`${APP}/`);

/**
 * Electron 44 会交给权限处理器的权限名(从 Electron Framework 的权限名表里逐个抄下来的,外加 media / midi / openExternal /
 * unknown)。新版本 Electron 多出来的名字默认就是拒绝;要放行得在这里和 web-permissions.cjs 一起想清楚。
 */
const ELECTRON_44_PERMISSIONS = [
  "automatic-fullscreen", "background-fetch", "background-sync", "clipboard-read", "clipboard-sanitized-write",
  "local-fonts", "hand-tracking", "idle-detection", "keyboardLock", "midiSysex", "notifications", "payment-handler",
  "periodic-background-sync", "persistent-storage", "geolocation", "pointerLock", "mediaKeySystem", "screen-wake-lock",
  "sensors", "storage-access", "system-wake-lock", "window-management", "display-capture", "top-level-storage-access",
  "captured-surface-control", "web-printing", "speaker-selection", "web-app-installation", "local-network-access",
  "local-network", "loopback-network", "geolocation-approximate", "deprecated-sync-clipboard-read", "fileSystem", "serial",
  "media", "midi", "fullscreen", "openExternal", "unknown",
];

describe("内嵌网页的权限:默认拒绝", () => {
  it("只放全屏、写剪贴板和几样只关乎登录态留不留得住的;读剪贴板、摄像头、麦克风、通知、定位、外部协议、本地网络一律不给", () => {
    const granted = ELECTRON_44_PERMISSIONS.filter((permission) => permissionAllowed({ trusted: false, permission }));
    expect(granted.sort()).toEqual(
      ["clipboard-sanitized-write", "fullscreen", "persistent-storage", "storage-access", "top-level-storage-access"].sort(),
    );
    expect(permissionAllowed({ trusted: false, permission: "openExternal", externalURL: "mailto:a@b.c" })).toBe(false);
  });

  it("装到会话上:请求、查询都按这一档答,设备(WebHID / Serial / USB)也不给", () => {
    const target = fakeSession();
    installPermissionPolicy(target, { isAppUrl: null });
    const page = { requestingUrl: "https://evil.example/landing", isMainFrame: true };
    for (const permission of ["clipboard-read", "media", "notifications", "geolocation", "midi", "openExternal"]) {
      expect(ask(target, permission, page), permission).toBe(false);
      expect(target.check!(null, permission, "https://evil.example", page), permission).toBe(false);
    }
    expect(ask(target, "fullscreen", page)).toBe(true);
    expect(ask(target, "clipboard-sanitized-write", page)).toBe(true);
    expect(target.device!()).toBe(false);
  });

  it("磁盘紧张时别清这个站的数据(persistent-storage):放 —— 拒了,发布账号的登录态可能被回收(抖音创作者平台就在要它)", () => {
    const target = fakeSession();
    const log = vi.fn();
    installPermissionPolicy(target, { isAppUrl: null, log });
    const douyin = { requestingUrl: "https://creator.douyin.com/creator-micro/home", isMainFrame: true };
    expect(ask(target, "persistent-storage", douyin)).toBe(true);
    expect(target.check!(null, "persistent-storage", "https://creator.douyin.com", douyin)).toBe(true);
    expect(log).not.toHaveBeenCalled();
    // 嵌在别的站里的登录框要它自己的 Cookie:放。
    expect(ask(target, "storage-access", { requestingUrl: "https://passport.example/login", isMainFrame: false })).toBe(true);
  });

  it("本地网络访问不给:那是公网网页去探本机后端、局域网的口子", () => {
    const target = fakeSession();
    installPermissionPolicy(target, { isAppUrl: null });
    for (const permission of ["local-network-access", "local-network", "loopback-network"]) {
      expect(ask(target, permission, { requestingUrl: "https://evil.example/", isMainFrame: true }), permission).toBe(false);
    }
  });

  it("就算网页停在和应用同一个地址上也不算应用自己:内嵌那一档根本没有「应用来源」", () => {
    const target = fakeSession();
    installPermissionPolicy(target, { isAppUrl: null });
    expect(ask(target, "media", { requestingUrl: `${APP}/#/home`, isMainFrame: true })).toBe(false);
  });

  it("拒绝时只记来源和权限名 —— 完整地址里可能带着令牌", () => {
    const target = fakeSession();
    const log = vi.fn();
    installPermissionPolicy(target, { isAppUrl: null, log });
    ask(target, "clipboard-read", { requestingUrl: "https://evil.example/cb?token=s3cret", isMainFrame: true });
    expect(log).toHaveBeenCalledWith("denied clipboard-read for https://evil.example");
    expect(JSON.stringify(log.mock.calls)).not.toContain("s3cret");
  });
});

describe("应用自己的页面", () => {
  it("录音录像、录屏、全屏、写剪贴板 —— 界面里真用到的;通知、定位、读剪贴板照样不给", () => {
    const granted = ELECTRON_44_PERMISSIONS.filter((permission) => permissionAllowed({ trusted: true, permission }));
    expect(granted.sort()).toEqual(["clipboard-sanitized-write", "display-capture", "fullscreen", "media", "persistent-storage"]);
  });

  it("外部协议只放 mailto:", () => {
    expect(permissionAllowed({ trusted: true, permission: "openExternal", externalURL: "mailto:hi@mosael.com" })).toBe(true);
    for (const url of ["ms-msdt:/id", "search-ms:query=x", "file:///etc/passwd", "weixin://dl", ""]) {
      expect(permissionAllowed({ trusted: true, permission: "openExternal", externalURL: url }), url).toBe(false);
    }
  });

  it("只认应用来源的主框架:别的来源、应用里嵌的子框架都按拒绝答", () => {
    const target = fakeSession();
    installPermissionPolicy(target, { isAppUrl });
    expect(ask(target, "media", { requestingUrl: `${APP}/#/media`, isMainFrame: true })).toBe(true);
    expect(ask(target, "media", { requestingUrl: `${APP}/#/media`, isMainFrame: false })).toBe(false);
    expect(ask(target, "media", { requestingUrl: "https://evil.example/", isMainFrame: true })).toBe(false);
    expect(target.check!(null, "media", APP, { requestingUrl: `${APP}/`, isMainFrame: true })).toBe(true);
    expect(target.check!(null, "media", "https://evil.example", { requestingUrl: "https://evil.example/" })).toBe(false);
  });

  it("查询里没带地址时看发起的那个页面(打包版 file:// 的来源只有 \"file://\")", () => {
    const target = fakeSession();
    installPermissionPolicy(target, { isAppUrl });
    const page = { getURL: () => `${APP}/#/home` };
    expect(target.check!(page, "media", "file://", {})).toBe(true);
    expect(target.check!({ getURL: () => "https://evil.example/" }, "media", "file://", {})).toBe(false);
  });
});

describe("main.cjs 的接法", () => {
  const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

  it("每个新会话一建出来就装内嵌那一档(默认拒绝),默认会话再换成应用那一档", () => {
    expect(MAIN).toMatch(/app\.on\("session-created",[\s\S]{0,200}installPermissionPolicy\(created, \{ isAppUrl: null/);
    expect(MAIN).toMatch(/installPermissionPolicy\(session\.defaultSession, \{ isAppUrl,/);
  });

  it("内嵌视图不自己另装处理器(一个会话只能有一个,后装的会盖掉默认拒绝)", () => {
    const publish = fs.readdirSync(path.join(__dirname, "publish")).filter((name) => /\.ts$/.test(name) && !/\.test\.ts$/.test(name));
    for (const name of publish) {
      expect(fs.readFileSync(path.join(__dirname, "publish", name), "utf8"), name).not.toMatch(/setPermission(Request|Check)Handler/);
    }
  });
});
