// 内嵌账号视图的 preload:只做反检测补丁。
//
// 返回主 UI 走内嵌浏览器工具栏(主窗口 HTML 的「← 返回 Mosael」+ Esc,见 accountViews.ts /
// App.tsx)——曾经往页面里注入过一个悬浮返回钮兜底 macOS 焦点吞点击,现已移除:工具栏那条本身
// 在主窗口视图里,不涉及跨 webContents 首点丢失,注入钮反而挡住平台页面右上角。
const { webFrame } = require("electron");

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
