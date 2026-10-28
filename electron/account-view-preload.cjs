// 内嵌账号视图的 preload:只做反检测补丁。
//
// 返回主 UI 走内嵌浏览器工具栏(主窗口 HTML 的「← 返回 Mosael」+ Esc,见 accountViews.ts /
// App.tsx)——曾经往页面里注入过一个悬浮返回钮兜底 macOS 焦点吞点击,现已移除:工具栏那条本身
// 在主窗口视图里,不涉及跨 webContents 首点丢失,注入钮反而挡住平台页面右上角。
const { webFrame, ipcRenderer } = require("electron");
//: **不能相对 require。** 这个 preload 跑在被沙箱化的账号视图里,Electron 的沙箱 preload
//: 只允许 `require("electron")`;`require("./ipc-contract.cjs")` 会在加载时抛错,后面整段补丁
//: (反检测、Passkey 防挂起、视频号登录探测)一行都不会执行。通道名与主进程契约的一致性由
//: `account-view-patches.test.ts` 对照 `ipc-contract.cjs` 守住。
const NET_PROBE_CHANNEL = "mosael:net-probe";

// 反检测:视图是 contextIsolation 的,preload 改 navigator 影响不到页面「主世界」——必须用
// webFrame.executeJavaScript 把补丁注进主世界,且趁 preload 执行(document_start 前、页面脚本跑之前)
// 尽早打上。抹掉最常被平台风控读取的自动化指纹:navigator.webdriver、缺失的 window.chrome /
// languages、plugins。
//
// **只补「Chromium 与真的 Chrome 不一样」的那几处,而且补成 Chrome 的样子。**
// 此前这里还伪造过 WebGL vendor/renderer(谎报 Intel —— 这台是 Apple Silicon)和 permissions.query
// 的返回(一个普通对象而不是 PermissionStatus),plugins 则是 `Plugin 1/2/3` 三个假名字。这比不补更
// 糟:反欺诈一比对就是「自称 Chrome、指纹却不是 Chrome」。X 的登录页一直挂「An unexpected error
// occurred」,排查到这一层(详见 browser/views/accountViews 的登录探针)。WebGL / permissions 现在不碰 ——
// Electron 与 Chrome 同为 ANGLE 渲染,原生值本就接近;plugins 补成 Chrome 真实报的 PDF 列表。
const STEALTH_JS = `(() => {
  const def = (obj, prop, get) => { try { Object.defineProperty(obj, prop, { get, configurable: true }); } catch (e) {} };
  def(Navigator.prototype, 'webdriver', () => false);
  try { if (!window.chrome) window.chrome = { runtime: {} }; } catch (e) {}
  try { if (!navigator.languages || !navigator.languages.length) def(Navigator.prototype, 'languages', () => ['zh-CN', 'zh']); } catch (e) {}
  //: Chrome 的 navigator.plugins 是 5 个 PDF Viewer 条目(内部 PDF 查看器),不是三个假名 ——
  //: 只补数量会漏出「Plugin 1」这种一眼假的名字。每条的 mimeTypes 里是 text/pdf 与 application/pdf。
  try {
    if (navigator.plugins && navigator.plugins.length === 0) {
      const mime = (type) => ({ type, suffixes: 'pdf', description: 'Portable Document Format' });
      const plugin = (name) => ({
        name,
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format',
        length: 2,
        0: mime('application/pdf'),
        1: mime('text/pdf'),
      });
      const names = ['PDF Viewer', 'Chrome PDF Viewer', 'Chromium PDF Viewer', 'Microsoft Edge PDF Viewer', 'WebKit built-in PDF'];
      def(Navigator.prototype, 'plugins', () => names.map(plugin));
    }
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

/**
 * 登录排障用的**网络探针**:把页面自己发出的请求结果(含响应体前 200 字)回报给主进程。
 *
 * 为什么必须在 preload:`webRequest` 只看得到状态码,看不到响应体,而「为什么这个会话被判无效」
 * 就写在登录接口的 JSON 里(errCode / 错误文案)。preload 在页面脚本之前跑,所以能罩住整条登录流程。
 *
 * 只报**微信这两个域**的同源请求,只留 origin+path,body 截断 —— 屏幕上不该出现别人的数据。
 */
const PROBE_HOSTS = ["channels.weixin.qq.com", "open.weixin.qq.com"];
try {
  const report = (url, status, body) => {
    try {
      const parsed = new URL(String(url), location.href);
      if (!PROBE_HOSTS.includes(parsed.hostname)) return;
      const text = typeof body === "string" ? body : "";
      ipcRenderer.send(NET_PROBE_CHANNEL, {
        path: parsed.pathname,
        status,
        body: text.slice(0, 200),
      });
    } catch (e) {
      /* 地址都解析不了,不报 */
    }
  };
  const originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = function patchedFetch(...args) {
      const target = args[0] && args[0].url ? args[0].url : args[0];
      const done = originalFetch.apply(this, args);
      try {
        done.then(
          (response) => {
            try {
              response.clone().text().then((text) => report(response.url || target, response.status, text)).catch(() => {});
            } catch (e) {}
          },
          () => {},
        );
      } catch (e) {}
      return done;
    };
  }
  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
    try {
      this.addEventListener("loadend", () => report(url, this.status, this.responseText));
    } catch (e) {}
    return originalOpen.call(this, method, url, ...rest);
  };
} catch (e) {
  /* 探针装不上不影响页面 */
}
