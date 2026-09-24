// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.mosaelPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");
const { IPC } = require("./ipc-contract.cjs");

/**
 * 订阅一条主进程事件,只把载荷交给回调。listener 的参数类型在这里写一次,免得每个
 * 订阅点各标一遍 —— checkJs 的 strict 对隐式 any 零容忍,而桥对象字面量上的类型
 * 标注只罩得住外层回调,罩不住里面这层 listener。
 * @template T
 * @param {string} channel
 * @param {(payload: T) => void} callback
 * @returns {() => void} 退订函数
 */
function onEvent(channel, callback) {
  /** @param {unknown} _event @param {T} payload */
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

// 全屏状态在渲染层挂载 React 监听器之前就可能推来(主进程 did-finish-load 时发一帧),
// 那一帧会错过 → 全屏时左上角边距"有时"没撤。这里在 preload 加载即订阅并缓存最新值,
// onFullscreen 订阅时先补发缓存,消除时序竞态。
let lastFullscreen = false;
ipcRenderer.on(IPC.event.fullscreen, (_event, value) => {
  lastFullscreen = Boolean(value);
});

// 通知点击 → 主进程要求打开任务中心。TaskCenter 监听的是 window 事件,这里做转发。
ipcRenderer.on(IPC.event.openTasks, () => {
  window.dispatchEvent(new CustomEvent("mosael:open-tasks"));
});

// mosael:// 深链与「拖到应用图标上的文件」。同样转成 window 事件,复用前端已有的
// 深链通道(lib/deepLink 的 gotoRecord / mosael:open-* 那套),不另起一套路由。
ipcRenderer.on(IPC.event.deepLink, (_event, link) => {
  window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: link }));
});
ipcRenderer.on(IPC.event.openFiles, (_event, paths) => {
  window.dispatchEvent(new CustomEvent("mosael:open-files", { detail: paths }));
});

// 界面语言 → 主进程。菜单、托盘、原生对话框、发布器回报的失败原因都是主进程自己说的话,
// 它得知道该说哪一种(见 i18n.cjs)。
//
// 契约是 **`<html lang>`**:渲染层本来就把界面语言写在那儿(见 frontend app/preferences),
// 那是网页声明「我是什么语言」的标准位置。盯着它,渲染层就不必为桌面壳多记一个调用 ——
// 漏记一处的话,那一处切了语言菜单还是旧的,而且不会报错。
//
// 只报**脚本写上去的**值:解析器带出来的 index.html 静态 lang 不产生 attributes 记录,
// 所以启动时不会先报一次静态的 zh-CN 再翻成真实语言,菜单不闪。偏好每次保存都会重写一遍
// lang(值不变也写),这里去重。观察 document 而不是 documentElement:preload 跑的时候
// <html> 可能还没解析出来。
let reportedLang = "";
new MutationObserver(() => {
  const lang = document.documentElement?.lang || "";
  if (!lang || lang === reportedLang) return;
  reportedLang = lang;
  ipcRenderer.send(IPC.send.locale, { locale: lang });
}).observe(document, { subtree: true, attributes: true, attributeFilter: ["lang"] });

// 桌面环境标识:前端据此加 is-desktop / is-mac 类,适配无边框窗(红绿灯占位、拖拽区)。
// setTitleOverlay:Win/Linux 的标题栏三键叠层颜色随主题切换(mac 无此叠层,调用为 no-op)。
/** @type {import("./preload-api").MosaelDesktopBridge} */
const desktopBridge = {
  platform: process.platform,
  setTitleOverlay: (colors) => ipcRenderer.send(IPC.send.titleOverlay, colors),
  // 系统能力:reportStatus 把「有几个任务在跑」推给主进程(托盘文案 + 有任务时阻止系统睡眠)。
  // 只推、不问 —— 系统层不认识后端,业务状态由知道它的这一侧负责告知。
  reportStatus: (status) => ipcRenderer.send(IPC.send.systemStatus, status),
  // 任务结束时通知系统层;窗口有焦点时主进程会跳过(应用内已有 toast)。
  notifyTask: (notice) => ipcRenderer.send(IPC.send.systemNotify, notice),
  getOpenAtLogin: () => ipcRenderer.invoke(IPC.invoke.getOpenAtLogin),
  setOpenAtLogin: (enabled) => ipcRenderer.invoke(IPC.invoke.setOpenAtLogin, enabled),
  recordingPermissions: {
    getStatus: (kind) => ipcRenderer.invoke(IPC.invoke.recordingStatus, kind),
    request: (kind) => ipcRenderer.invoke(IPC.invoke.recordingRequest, kind),
    openSettings: (kind) => ipcRenderer.invoke(IPC.invoke.recordingOpenSettings, kind),
  },
  data: {
    exportDiagnostics: () => ipcRenderer.invoke(IPC.invoke.dataExportDiagnostics),
    createBackup: (token) => ipcRenderer.invoke(IPC.invoke.dataCreateBackup, { token }),
    applyRestore: (stageId) => ipcRenderer.invoke(IPC.invoke.dataApplyRestore, { stageId }),
  },
  // 更新:checkUpdates 主动查(设置页按钮);onUpdateAvailable 订阅启动静默检查的结果。
  checkUpdates: () => ipcRenderer.invoke(IPC.invoke.checkUpdates),
  onUpdateAvailable: (callback) => onEvent(IPC.event.updateAvailable, callback),
  // 全屏状态订阅:主进程在进入/退出全屏(及首帧)推送布尔值。订阅时立即补发缓存的当前值,
  // 避免渲染层挂载晚于首帧推送时"有时"漏掉全屏态。
  // 自定义 CSS(userData/custom.css)。read 取当前内容,onChange 订阅存盘后的推送 ——
  // 「改一下就生效」靠的是后者,而不是让渲染层去轮询文件。
  customCss: {
    read: () => ipcRenderer.invoke(IPC.invoke.customCssRead),
    path: () => ipcRenderer.invoke(IPC.invoke.customCssPath),
    open: () => ipcRenderer.invoke(IPC.invoke.customCssOpen),
    reveal: () => ipcRenderer.invoke(IPC.invoke.customCssReveal),
    onChange: (callback) => onEvent(IPC.event.customCss, callback),
  },
  onFullscreen: (callback) => {
    callback(lastFullscreen);
    return onEvent(IPC.event.fullscreen, callback);
  },
};
contextBridge.exposeInMainWorld("mosaelDesktop", desktopBridge);

/** @type {import("./preload-api").MosaelPublishBridge} */
const publishBridge = {
  login: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishLogin, { accountId, platform }),
  openPage: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishOpenPage, { accountId, platform }),
  signOut: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishSignOut, { accountId, platform }),
  inspect: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishInspect, { accountId, platform }),
  navigate: (url) => ipcRenderer.invoke(IPC.invoke.publishNavigate, { url }),
  back: () => ipcRenderer.invoke(IPC.invoke.publishBack),
  forward: () => ipcRenderer.invoke(IPC.invoke.publishForward),
  reload: () => ipcRenderer.invoke(IPC.invoke.publishReload),
  hideView: () => ipcRenderer.invoke(IPC.invoke.publishHideView),
  onViewState: (callback) => onEvent(IPC.event.publishView, callback),
  /** 悬浮卡片几何(见 main.cjs onPanels):渲染层照它画圆角/阴影/标题条。 */
  /** 拖动/缩放悬浮面板(几何由主进程持有并落盘)。 */
  setPanelLayout: (patch) => ipcRenderer.invoke(IPC.invoke.publishPanelLayout, patch),
  /** 手动关闭某块面板:只撤面板,任务照常继续。 */
  closePanel: (id) => ipcRenderer.invoke(IPC.invoke.publishClosePanel, { id }),
  onPanels: (callback) => onEvent(IPC.event.publishPanels, callback),
};
contextBridge.exposeInMainWorld("mosaelPublish", publishBridge);

// 自动化浏览器(RPA / 智能体)的实时预览帧:离屏视图截帧,前端画成缩略预览。
/** @type {import("./preload-api").MosaelBrowserBridge} */
const browserBridge = {
  onFrame: (callback) => onEvent(IPC.event.browserFrame, callback),
  // 通用池档案登录:在该档案分区开内嵌视图登任意站点(见 main.cjs browser:openLogin)。
  openLogin: (opts) => ipcRenderer.invoke(IPC.invoke.browserOpenLogin, opts),
  clearProfile: (partition) => ipcRenderer.invoke(IPC.invoke.browserClearProfile, { partition }),
};
contextBridge.exposeInMainWorld("mosaelBrowser", browserBridge);
