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
  // **WebAuthn:当场说不,不要让页面一直转。**
  //
  // 这个视图里 passkey 走不通,而且是三条路各自走不通:
  //   * 平台认证器(Touch ID)默认不受理 —— 要 app.configureWebAuthn 才开,而它存的是
  //     设备绑定、不跟 iCloud 同步的凭据,救不了用户已有的那把 passkey;
  //   * 手机/跨设备(hybrid)要一个扫码或蓝牙的选择界面,Electron 不提供 —— 请求就悬在那儿;
  //   * 多凭据选择走 session 的 select-webauthn-account,没有监听者时才会被取消。
  //
  // 结果就是 Google 停在「Complete sign-in using your passkey」一直转,而右下角那个
  // 「Try another way」得用户自己发现。当场 reject 一个 NotAllowedError 之后,站点自己的
  // 回退路径(密码 + 两步验证)就会接上 —— **这不降低安全性**,只是拒绝一种此处用不了的方式。
  //
  // 哪天 Electron 把这几条补齐(或我们决定开 Touch ID),这一段就该删掉。
  try {
    if (window.PublicKeyCredential) {
      window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
      window.PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
    }
    const store = navigator.credentials;
    if (store) {
      const decline = () =>
        Promise.reject(new DOMException('This browser has no available authenticator.', 'NotAllowedError'));
      const get = store.get && store.get.bind(store);
      const create = store.create && store.create.bind(store);
      // 只拦 publicKey 那一种 —— 密码和联合登录凭据照常走。
      if (get) store.get = (options) => (options && options.publicKey ? decline() : get(options));

      if (create) store.create = (options) => (options && options.publicKey ? decline() : create(options));
    }
  } catch (e) {}
})();`;
try {
  void webFrame.executeJavaScript(STEALTH_JS);
} catch (e) {
  /* 注入失败不影响自动化主流程 */
}
