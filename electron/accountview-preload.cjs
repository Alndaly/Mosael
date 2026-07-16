// 内嵌账号视图的 preload:往平台页面里注入一个「← 返回 Mibu」悬浮按钮。
//
// 为什么需要:内嵌账号视图(WebContentsView)与主 UI 是同级视图。用户在平台页面里点过之后,输入
// 焦点在账号视图上;此时点主 UI 顶栏的「返回」,macOS 会把「首次点击」用于切换 web contents 的焦点
// 而吞掉那次点击(偶发失灵)。把返回按钮做进账号视图本身,点击就永远发生在「当前聚焦的视图」内,
// 100% 生效。顶栏那个「返回」和 Esc 仍保留作双保险。
const { ipcRenderer, webFrame } = require("electron");

// 反检测:视图是 contextIsolation 的,preload 改 navigator 影响不到页面「主世界」——必须用
// webFrame.executeJavaScript 把补丁注进主世界,且趁 preload 执行(document_start 前、页面脚本跑之前)
// 尽早打上。抹掉最常被平台风控读取的自动化指纹:navigator.webdriver、缺失的 window.chrome / plugins /
// languages、permissions.query 行为、WebGL vendor/renderer。治标不治本,但比只抹 UA 里的 Electron 字样强。
const STEALTH_JS = `(() => {
  const def = (obj, prop, get) => { try { Object.defineProperty(obj, prop, { get, configurable: true }); } catch (e) {} };
  def(Navigator.prototype, 'webdriver', () => false);
  try { if (!window.chrome) window.chrome = { runtime: {} }; } catch (e) {}
  try { if (!navigator.languages || !navigator.languages.length) def(Navigator.prototype, 'languages', () => ['zh-CN', 'zh']); } catch (e) {}
  try {
    if (navigator.plugins && navigator.plugins.length === 0)
      def(Navigator.prototype, 'plugins', () => [1, 2, 3].map((i) => ({ name: 'Plugin ' + i })));
  } catch (e) {}
  try {
    const q = navigator.permissions && navigator.permissions.query;
    if (q) navigator.permissions.query = (p) =>
      p && p.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : q.call(navigator.permissions, p);
  } catch (e) {}
  try {
    const patch = (proto) => {
      if (!proto) return;
      const g = proto.getParameter;
      proto.getParameter = function (p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return g.call(this, p);
      };
    };
    patch(window.WebGLRenderingContext && window.WebGLRenderingContext.prototype);
    patch(window.WebGL2RenderingContext && window.WebGL2RenderingContext.prototype);
  } catch (e) {}
})();`;
try {
  void webFrame.executeJavaScript(STEALTH_JS);
} catch (e) {
  /* 注入失败不影响自动化主流程 */
}

const BTN_ID = "__mibu_exit_btn";

// 返回按钮文案跟随应用语言。preload 在平台页面的渲染进程里跑,拿不到 userData 路径,
// 同步问主进程一次即可(语言切换会整页重载,不需要热更新)。
const LOCALE = (() => {
  try {
    return ipcRenderer.sendSync("app:getLocale") === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
})();
const EXIT_LABEL = LOCALE === "en" ? "← Back to Mibu" : "← 返回 Mibu"; // i18n-ok 主进程词典外的双语常量

function injectExitButton() {
  try {
    if (!document.documentElement) return;
    if (document.getElementById(BTN_ID)) return;
    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.textContent = EXIT_LABEL;
    Object.assign(btn.style, {
      position: "fixed",
      top: "10px",
      right: "16px",
      zIndex: "2147483647", // 盖在平台页面一切之上
      padding: "6px 12px",
      borderRadius: "999px",
      border: "1px solid rgba(255,255,255,.18)",
      background: "rgba(17,20,26,.92)",
      color: "#e6eaf0",
      font: "600 12px/1 system-ui, -apple-system, 'PingFang SC', sans-serif",
      cursor: "pointer",
      boxShadow: "0 4px 16px rgba(0,0,0,.35)",
      WebkitAppRegion: "no-drag",
    });
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      ipcRenderer.send("publish:exit"); // 主进程收到 → 收起内嵌视图,把窗口还给 UI
    });
    document.documentElement.appendChild(btn);
  } catch {
    /* 注入失败不影响自动化主流程 */
  }
}

// 每次导航后(平台页面常是 SPA,也监听一下)重新注入。
window.addEventListener("DOMContentLoaded", injectExitButton);
window.addEventListener("load", injectExitButton);
// 平台 SPA 可能重绘掉我们的按钮 —— 定时补一下(便宜,2s 一次)。
setInterval(injectExitButton, 2000);
