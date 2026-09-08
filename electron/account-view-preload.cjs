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
  // **WebAuthn:有认证器就放行,没有就当场说不 —— 唯独不能一直挂着。**
  //
  // Electron 44 只给了两条:平台认证器(app.configureWebAuthn,需要签名 + entitlement)和
  // 多凭据选择(session 的 select-webauthn-account,主进程已接)。**没给的是手机/跨设备
  // (hybrid,扫码那条)** —— 它的二维码载荷和蓝牙广播都在 Chromium 内部生成,Electron 没有
  // 暴露任何挂钩。所以那条路我们做不出界面,而 Chromium 又不会替我们报错:请求就那么悬着,
  // 页面停在「Complete sign-in using your passkey」一直转。
  //
  // 于是分两种情况:
  //   有平台认证器 → 正常走(Touch ID 弹框、多凭据由主进程选),不插手;
  //   没有         → 剩下的只可能是 hybrid,**必挂**,当场 reject 让站点回退到密码。
  //
  // 再加一道兜底超时:即使有认证器,某些请求仍可能落到没有 UI 的传输上。宁可等久一点也不能
  // 无限等 —— 45 秒足够按下 Touch ID,又不至于让人以为应用死了。
  try {
    const store = navigator.credentials;
    const available = () => {
      try {
        return window.PublicKeyCredential
          ? window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
          : Promise.resolve(false);
      } catch (e) {
        return Promise.resolve(false);
      }
    };
    const refuse = () =>
      new DOMException('This browser has no usable authenticator.', 'NotAllowedError');
    const guard = (real) => (options) => {
      if (!options || !options.publicKey) return real(options);   // 密码/联合登录凭据不管
      return available().then((ok) => {
        if (!ok) return Promise.reject(refuse());
        return Promise.race([
          real(options),
          new Promise((_, reject) => setTimeout(() => reject(refuse()), 45000)),
        ]);
      });
    };
    if (store && store.get) store.get = guard(store.get.bind(store));
    if (store && store.create) store.create = guard(store.create.bind(store));
    // 条件式 UI(自动填充里的 passkey)在这里同样没有承载它的界面。
    if (window.PublicKeyCredential)
      window.PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
  } catch (e) {}
})();`;
try {
  void webFrame.executeJavaScript(STEALTH_JS);
} catch (e) {
  /* 注入失败不影响自动化主流程 */
}
