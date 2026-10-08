"use strict";

/**
 * 「应用自己的页面」是哪些,以及主窗口只许停在它们上面。
 *
 * 主窗口挂着 preload 的四座桥(mosaelDesktop / mosaelPublish / mosaelBrowser / mosaelPageTools):恢复备份、导出诊断包、
 * 开登录视图、抓页面图片……主进程收到调用不问是谁 —— 那么主框架一旦落到别的来源(一个漏了 target 的链接、以后写的什么代码),
 * 那个页面就拿到了全部能力;打包版里它发往本机后端的请求还会被自动带上壳令牌。
 *
 * 所以三道,都按同一个「应用来源」判:
 * - 主窗口的主框架只许导航到应用自己的地址,别的拦下(http(s) 交给系统浏览器,和 setWindowOpenHandler 一样);
 * - IPC 只收主窗口自己那个主框架、停在应用地址上时发来的;
 * - 壳令牌只加在应用页面发出的请求上。
 *
 * 应用的地址:开发时是 Vite 那个来源(`MOSAEL_FRONTEND_URL`),打包后是 `frontend/dist/` 下的文件(hash 路由,
 * 地址恒为 `…/dist/index.html#/…`;浮层视图是同目录的 float-layer.html)。
 */
const path = require("node:path");
const { pathToFileURL } = require("node:url");

/**
 * @param {{ isPackaged: boolean, frontendUrl: string, distDir: string }} options
 * @returns {(raw: unknown) => boolean}
 */
function createAppUrlCheck({ isPackaged, frontendUrl, distDir }) {
  if (!isPackaged) {
    const origin = new URL(frontendUrl).origin;
    return (raw) => {
      try {
        return new URL(String(raw)).origin === origin;
      } catch {
        return false;
      }
    };
  }
  // 比路径而不是比字符串前缀:URL 已经把 `..`、%2e 这类规整过,pathname 解码之后落在 dist 目录里才算。
  const base = decodeURIComponent(pathToFileURL(distDir + path.sep).pathname);
  return (raw) => {
    try {
      const url = new URL(String(raw));
      return url.protocol === "file:" && !url.host && decodeURIComponent(url.pathname).startsWith(base);
    } catch {
      return false;
    }
  };
}

/**
 * 主窗口的主框架只许导航到应用自己的地址。拦下的 http(s) 交给系统浏览器;别的(file:、自定义协议)什么都不做。
 * Electron 25 起这两个事件的第一个参数就是带 `url` 的事件对象,老的第二个参数仍在,两种都认。
 * @param {Pick<Electron.WebContents, "on">} contents
 * @param {{ isAppUrl: (url: string) => boolean, openExternal: (url: string) => void, log?: (line: string) => void }} options
 */
function guardNavigation(contents, { isAppUrl, openExternal, log = () => undefined }) {
  const block = (kind, event, legacyUrl, handOff) => {
    const url = String(event?.url ?? legacyUrl ?? "");
    if (isAppUrl(url)) return;
    event.preventDefault();
    let shown = "";
    try {
      shown = new URL(url).protocol === "file:" ? "file:" : new URL(url).origin;
    } catch {
      shown = "unparsable url";
    }
    log(`blocked ${kind} to ${shown}`);
    if (handOff && /^https?:\/\//i.test(url)) openExternal(url);
  };
  contents.on("will-navigate", (event, url) => block("navigation", event, url, true));
  // 重定向不是人点的:拦下就好,不替它开外部浏览器。
  contents.on("will-redirect", (event, url) => block("redirect", event, url, false));
}

/**
 * IPC 的调用方是不是应用自己:主窗口自己的 webContents、主框架、停在应用地址上。浮层视图没有 preload,内嵌网页的
 * preload 不暴露 ipcRenderer,所以正常只有主窗口会发来;这一道防的是主框架被导航走之后的那种情形。
 * @param {{ isAppUrl: (url: string) => boolean, windowOf: (contents: Electron.WebContents) => { webContents: Electron.WebContents } | null }} options
 * @returns {(event: Pick<Electron.IpcMainEvent, "sender" | "senderFrame">) => boolean}
 */
function createSenderCheck({ isAppUrl, windowOf }) {
  return (event) => {
    const frame = event?.senderFrame;
    // 框架已经没了(导航走、销毁)时 senderFrame 是 null;子框架有 parent。
    if (!frame || frame.parent) return false;
    if (windowOf(event.sender)?.webContents !== event.sender) return false;
    return isAppUrl(frame.url);
  };
}

module.exports = { createAppUrlCheck, createSenderCheck, guardNavigation };
