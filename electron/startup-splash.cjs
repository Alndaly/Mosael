"use strict";

/**
 * 后端还没就绪时的「正在启动」小窗。
 *
 * 首次打开(系统要扫一遍整个安装包)、升级之后的数据迁移,后端可能要好几分钟才就绪。此前壳固定等 30 秒,过了就弹
 * 「启动失败」并退出 —— 而后端其实还在干活。现在只要后端进程活着就等(见 backend-lifecycle 的 waitReady),
 * 等得久了亮这个小窗:已经等了多久、后端日志的最后一行(看得出它在迁移还是在装插件),一个「退出」。
 *
 * 页面是写死的 data: URL,不挂 preload、不导航;数字和日志行经 executeJavaScript 以 JSON 交进去,不拼 HTML。
 * 人点「退出」或关掉它 = 不等了,退出应用。
 */
const fs = require("node:fs");

/** 日志里一行的样子:`2026-10-08 11:08:51 INFO    app.main: Mosael backend starting …` —— 只留冒号后面那句。 */
const LOG_LINE = /^\d{4}-\d{2}-\d{2}[ T][\d:.,]+\s+(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+[\w.]+:\s*(.*)$/;

/**
 * 后端日志的最后一句话(读文件尾部几 KB)。只认带时间和级别的那种行 —— traceback 的续行、uvicorn 的访问日志不算。
 * @param {string} file
 * @param {number} [maxChars]
 */
function lastLogLine(file, maxChars = 140) {
  let text = "";
  try {
    const stat = fs.statSync(file);
    const size = Math.min(stat.size, 8192);
    const buffer = Buffer.alloc(size);
    const fd = fs.openSync(file, "r");
    try {
      fs.readSync(fd, buffer, 0, size, stat.size - size);
    } finally {
      fs.closeSync(fd);
    }
    text = buffer.toString("utf8");
  } catch {
    return "";
  }
  const lines = text.split(/\r?\n/);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const match = LOG_LINE.exec(lines[index].trim());
    if (match && match[1]) return match[1].length > maxChars ? `${match[1].slice(0, maxChars - 1)}…` : match[1];
  }
  return "";
}

/**
 * 小窗的页面。文案经 JSON 嵌进脚本、由脚本写进 textContent,不拼进 HTML。
 * @param {{ title: string, body: string, quit: string, lang: string }} strings
 */
function splashHtml(strings) {
  return `<!doctype html>
<html lang="${strings.lang === "en" ? "en" : "zh-CN"}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<style>
  :root { color-scheme: light dark; --bg: #f7f8fa; --fg: #1f2329; --muted: #646a73; --line: #dee0e3; --accent: #4a63a8; }
  @media (prefers-color-scheme: dark) { :root { --bg: #1f2125; --fg: #e8eaed; --muted: #9aa0a6; --line: #3c4043; --accent: #8ab4f8; } }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font: 13px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
  main { box-sizing: border-box; height: 100%; padding: 22px 24px 18px; display: grid; grid-template-rows: auto auto 1fr auto; gap: 6px; }
  h1 { margin: 0; font-size: 15px; font-weight: 600; }
  p { margin: 0; color: var(--muted); }
  #log { font: 11px/1.5 ui-monospace, Menlo, Consolas, monospace; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; align-self: end; }
  footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid var(--line); padding-top: 10px; }
  #elapsed { color: var(--muted); font-variant-numeric: tabular-nums; }
  button { font: inherit; padding: 4px 14px; border-radius: 6px; border: 1px solid var(--line); background: transparent; color: var(--fg); cursor: pointer; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
</style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p id="body"></p>
  <div id="log"></div>
  <footer><span id="elapsed"></span><button id="quit" type="button"></button></footer>
</main>
<script>
  const strings = ${JSON.stringify(strings).replace(/</g, "\\u003c")};
  document.getElementById("title").textContent = strings.title;
  document.getElementById("body").textContent = strings.body;
  document.getElementById("quit").textContent = strings.quit;
  document.getElementById("quit").addEventListener("click", () => window.close());
  window.setStatus = (status) => {
    document.getElementById("elapsed").textContent = status.elapsed || "";
    document.getElementById("log").textContent = status.log || "";
    if (status.body) document.getElementById("body").textContent = status.body;
  };
</script>
</body>
</html>`;
}

/**
 * @param {{
 *   BrowserWindow: typeof import("electron").BrowserWindow,
 *   strings: { title: string, body: string, quit: string, lang: string },
 *   onQuit: () => void,
 * }} options
 */
function createStartupSplash({ BrowserWindow, strings, onQuit }) {
  /** @type {import("electron").BrowserWindow | null} */
  let win = null;
  let closingOurselves = false;
  return {
    show() {
      if (win) return;
      win = new BrowserWindow({
        width: 460,
        height: 210,
        resizable: false,
        minimizable: false,
        maximizable: false,
        fullscreenable: false,
        title: "Mosael",
        show: false,
        backgroundColor: "#f7f8fa",
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
      });
      win.setMenuBarVisibility(false);
      win.webContents.on("will-navigate", (event) => event.preventDefault());
      win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      win.once("ready-to-show", () => win?.show());
      win.on("closed", () => {
        win = null;
        if (!closingOurselves) onQuit();
      });
      void win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(splashHtml(strings))}`);
    },
    /** @param {{ elapsed: string, log: string, body?: string }} status */
    update(status) {
      if (!win || win.isDestroyed()) return;
      void win.webContents.executeJavaScript(`window.setStatus?.(${JSON.stringify(status)})`).catch(() => undefined);
    },
    close() {
      if (!win || win.isDestroyed()) return;
      closingOurselves = true;
      win.close();
    },
    get shown() {
      return Boolean(win);
    },
  };
}

module.exports = { createStartupSplash, lastLogLine, splashHtml };
