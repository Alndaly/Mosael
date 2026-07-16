// 内嵌账号视图的「拟真」补丁:让 Electron 内嵌浏览器看起来像一个正常的桌面 Chrome,
// 避免平台风控把「用户自己授权的自动化发布」误判为爬虫/机器人而拦截。
//
// 注入方式:CDP Page.addScriptToEvaluateOnNewDocument —— 在每个新文档最早期(document_start)、
// 页面主世界执行,先于平台自己的检测脚本。补的是业界公认的 Electron/无头特征差异点。

/** 在页面主世界最早期执行的补丁脚本(纯字符串,经 CDP 注入)。 */
export const STEALTH_SOURCE = String.raw`
(() => {
  try {
    // 1) navigator.webdriver:自动化标志,正常浏览器为 false。删掉 getter 让它返回 undefined/false。
    try {
      Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false, configurable: true });
    } catch (_) {}
    try { delete Navigator.prototype.webdriver; } catch (_) {}

    // 2) window.chrome:真实 Chrome 有这个对象,无头/精简内核常缺失。补一个最小可信版本。
    if (!window.chrome) {
      window.chrome = {};
    }
    if (!window.chrome.runtime) {
      window.chrome.runtime = {};
    }
    if (!window.chrome.app) {
      window.chrome.app = { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } };
    }

    // 3) navigator.languages:无头常为空或单一。给中文桌面常见值。
    try {
      Object.defineProperty(Navigator.prototype, 'languages', { get: () => ['zh-CN', 'zh', 'en'], configurable: true });
    } catch (_) {}

    // 4) navigator.plugins / mimeTypes:无头为空数组是明显特征。伪造一个非空、带常见 PDF 插件的列表。
    try {
      const makePlugin = (name, filename, desc) => {
        const plugin = { name: name, filename: filename, description: desc, length: 1 };
        Object.defineProperty(plugin, '0', { value: { type: 'application/pdf', suffixes: 'pdf', description: desc, enabledPlugin: plugin }, enumerable: true });
        return plugin;
      };
      const plugins = [
        makePlugin('Chrome PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format'),
        makePlugin('Chrome PDF Viewer', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', ''),
        makePlugin('Native Client', 'internal-nacl-plugin', ''),
      ];
      plugins.item = (i) => plugins[i] || null;
      plugins.namedItem = (n) => plugins.find((p) => p.name === n) || null;
      plugins.refresh = () => {};
      Object.defineProperty(Navigator.prototype, 'plugins', { get: () => plugins, configurable: true });
    } catch (_) {}

    // 5) permissions.query('notifications'):无头会返回与真实浏览器不一致的状态,平台以此判活。对齐真实行为。
    try {
      const original = window.navigator.permissions && window.navigator.permissions.query;
      if (original) {
        window.navigator.permissions.query = (params) =>
          params && params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission, onchange: null })
            : original.call(window.navigator.permissions, params);
      }
    } catch (_) {}

    // 6) WebGL vendor/renderer:无头/软件渲染会暴露 'Google SwiftShader' / 'Google Inc.',真机是显卡厂商。
    //    改成常见的 Intel/Apple 值,消除软件渲染特征。
    try {
      const spoof = { 37445: 'Intel Inc.', 37446: 'Intel Iris OpenGL Engine' }; // UNMASKED_VENDOR/RENDERER
      const patch = (proto) => {
        if (!proto) return;
        const getParam = proto.getParameter;
        proto.getParameter = function (param) {
          if (param in spoof) return spoof[param];
          return getParam.call(this, param);
        };
      };
      patch(window.WebGLRenderingContext && window.WebGLRenderingContext.prototype);
      patch(window.WebGL2RenderingContext && window.WebGL2RenderingContext.prototype);
    } catch (_) {}

    // 7) navigator.hardwareConcurrency / deviceMemory:给桌面常见值(无头有时为 1)。
    try {
      if (!navigator.hardwareConcurrency || navigator.hardwareConcurrency < 2) {
        Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => 8, configurable: true });
      }
      if ('deviceMemory' in navigator && !navigator.deviceMemory) {
        Object.defineProperty(Navigator.prototype, 'deviceMemory', { get: () => 8, configurable: true });
      }
    } catch (_) {}
  } catch (_) {
    /* 补丁失败不影响页面加载 */
  }
})();
`;
