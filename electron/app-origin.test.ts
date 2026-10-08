import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
const { createAppUrlCheck, createSenderCheck, guardNavigation } = createRequire(import.meta.url)("./app-origin.cjs") as {
  createAppUrlCheck: (options: { isPackaged: boolean; frontendUrl: string; distDir: string }) => (raw: unknown) => boolean;
  createSenderCheck: (options: { isAppUrl: (url: string) => boolean; windowOf: (contents: unknown) => { webContents: unknown } | null }) => (event: unknown) => boolean;
  guardNavigation: (contents: EventEmitter, options: { isAppUrl: (url: string) => boolean; openExternal: (url: string) => void; log?: (line: string) => void }) => void;
};

const DIST = path.join(path.sep, "Applications", "Mosael.app", "Contents", "Resources", "app.asar", "frontend", "dist");
const fileUrl = (...parts: string[]) => pathToFileURL(path.join(...parts)).href;

describe("应用自己的地址", () => {
  it("开发时:和 Vite 同一个来源才算", () => {
    const isApp = createAppUrlCheck({ isPackaged: false, frontendUrl: "http://127.0.0.1:5173", distDir: DIST });
    expect(isApp("http://127.0.0.1:5173/#/home")).toBe(true);
    expect(isApp("http://127.0.0.1:5173/float-layer.html")).toBe(true);
    expect(isApp("http://127.0.0.1:5174/")).toBe(false);
    expect(isApp("http://localhost:5173/")).toBe(false);
    expect(isApp("https://evil.example/")).toBe(false);
    expect(isApp(fileUrl(DIST, "index.html"))).toBe(false);
    expect(isApp("not a url")).toBe(false);
    expect(isApp(undefined)).toBe(false);
  });

  it("打包后:dist 目录里的文件才算,目录外的文件、跳出目录的路径、别的协议都不算", () => {
    const isApp = createAppUrlCheck({ isPackaged: true, frontendUrl: "http://127.0.0.1:5173", distDir: DIST });
    expect(isApp(`${fileUrl(DIST, "index.html")}#/editor?p=1`)).toBe(true);
    expect(isApp(fileUrl(DIST, "float-layer.html"))).toBe(true);
    expect(isApp(fileUrl(path.sep, "Users", "me", "Downloads", "dropped.html"))).toBe(false);
    expect(isApp(`${fileUrl(DIST)}/../../secret.html`)).toBe(false);
    expect(isApp(`${fileUrl(DIST)}/%2e%2e/secret.html`)).toBe(false);
    expect(isApp(`${fileUrl(DIST)}-evil/index.html`)).toBe(false);
    expect(isApp("http://127.0.0.1:5173/")).toBe(false);
    expect(isApp(`file://attacker-host${new URL(fileUrl(DIST, "index.html")).pathname}`)).toBe(false);
  });
});

/** 一个像 webContents 那样发 will-navigate / will-redirect 的东西;事件对象带 url 和 preventDefault(Electron 25 起的形状)。 */
function navigate(contents: EventEmitter, kind: "will-navigate" | "will-redirect", url: string, legacy = false) {
  const event = { url: legacy ? undefined : url, preventDefault: vi.fn() };
  contents.emit(kind, event, url);
  return event.preventDefault.mock.calls.length > 0;
}

describe("主窗口只许停在应用自己的地址上", () => {
  const isAppUrl = (url: string) => url.startsWith("http://127.0.0.1:5173/");

  it("应用自己的地址放行;别的来源拦下,http(s) 交给系统浏览器", () => {
    const contents = new EventEmitter();
    const openExternal = vi.fn();
    guardNavigation(contents, { isAppUrl, openExternal });
    expect(navigate(contents, "will-navigate", "http://127.0.0.1:5173/#/plugins")).toBe(false);
    expect(navigate(contents, "will-navigate", "https://evil.example/phish")).toBe(true);
    expect(openExternal).toHaveBeenCalledWith("https://evil.example/phish");
  });

  it("拖进窗口的文件、自定义协议:拦下,什么都不开", () => {
    const contents = new EventEmitter();
    const openExternal = vi.fn();
    guardNavigation(contents, { isAppUrl, openExternal });
    expect(navigate(contents, "will-navigate", "file:///Users/me/Downloads/dropped.html")).toBe(true);
    expect(navigate(contents, "will-navigate", "javascript:alert(1)")).toBe(true);
    expect(navigate(contents, "will-navigate", "weixin://dl/business")).toBe(true);
    expect(openExternal).not.toHaveBeenCalled();
  });

  it("重定向到别处:拦下,不替它开浏览器(不是人点的)", () => {
    const contents = new EventEmitter();
    const openExternal = vi.fn();
    guardNavigation(contents, { isAppUrl, openExternal });
    expect(navigate(contents, "will-redirect", "https://evil.example/")).toBe(true);
    expect(openExternal).not.toHaveBeenCalled();
  });

  it("老的 (event, url) 参数形状一样认", () => {
    const contents = new EventEmitter();
    guardNavigation(contents, { isAppUrl, openExternal: vi.fn() });
    expect(navigate(contents, "will-navigate", "https://evil.example/", true)).toBe(true);
    expect(navigate(contents, "will-navigate", "http://127.0.0.1:5173/", true)).toBe(false);
  });

  it("记日志只记来源,不记完整地址", () => {
    const contents = new EventEmitter();
    const log = vi.fn();
    guardNavigation(contents, { isAppUrl, openExternal: vi.fn(), log });
    navigate(contents, "will-navigate", "https://evil.example/x?token=s3cret");
    expect(log).toHaveBeenCalledWith("blocked navigation to https://evil.example");
  });
});

describe("IPC 只收应用自己的主框架发来的", () => {
  const isAppUrl = (url: string) => url.startsWith("http://127.0.0.1:5173/");
  const host = { id: 1 };
  const view = { id: 2 };
  const windowOf = (contents: unknown) => (contents === host ? { webContents: host } : contents === view ? { webContents: host } : null);
  const check = createSenderCheck({ isAppUrl, windowOf });
  const frame = (url: string, parent: unknown = null) => ({ url, parent });

  it("主窗口自己、主框架、停在应用地址上:收", () => {
    expect(check({ sender: host, senderFrame: frame("http://127.0.0.1:5173/#/home") })).toBe(true);
  });

  it("主框架被导航到别的来源:不收", () => {
    expect(check({ sender: host, senderFrame: frame("https://evil.example/") })).toBe(false);
  });

  it("子框架(应用里嵌的 iframe)、框架已经没了:不收", () => {
    expect(check({ sender: host, senderFrame: frame("http://127.0.0.1:5173/", frame("http://127.0.0.1:5173/")) })).toBe(false);
    expect(check({ sender: host, senderFrame: null })).toBe(false);
  });

  it("挂在主窗口上的别的视图(内嵌网页、浮层)、不属于任何窗口的:不收", () => {
    expect(check({ sender: view, senderFrame: frame("http://127.0.0.1:5173/") })).toBe(false);
    expect(check({ sender: { id: 3 }, senderFrame: frame("http://127.0.0.1:5173/") })).toBe(false);
  });
});

describe("main.cjs 的接法", () => {
  const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

  it("所有 IPC 处理器都经 handle / listen 注册,不直接用 ipcMain", () => {
    expect(MAIN.match(/ipcMain\.(handle|on)\(/g)).toEqual(["ipcMain.handle(", "ipcMain.on("]);
    expect(MAIN).toMatch(/ipcMain\.handle\(channel, \(event, \.\.\.args\) => \{\s*if \(!fromAppWindow\(event\)\)/);
    expect(MAIN).toMatch(/ipcMain\.on\(channel, \(event, \.\.\.args\) => \{\s*if \(!fromAppWindow\(event\)\)/);
  });

  it("主窗口装了导航拦截;壳令牌只加在应用页面发出的请求上", () => {
    expect(MAIN).toMatch(/guardNavigation\(win\.webContents, \{\s*isAppUrl,/);
    expect(MAIN).toMatch(/onBeforeSendHeaders\([\s\S]{0,400}if \(!isAppUrl\(from\)\) \{\s*callback\(\{\}\);/);
  });
});
