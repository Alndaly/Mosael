// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.mosaelPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");
const { IPC } = require("./ipc-contract.cjs");
const { humanIpcError } = require("./ipc-errors.cjs");

/**
 * 调主进程。**失败时给人看的话在这里统一整理**(见 ipc-errors.cjs):不露 Electron 的「Error invoking remote
 * method …」前缀和堆栈;主进程里没有这个处理器(主进程是旧的)时说要重启。语言跟着页面(`<html lang>`)。
 * @param {string} channel
 * @param {...unknown} args
 */
function invoke(channel, ...args) {
  return ipcRenderer.invoke(channel, ...args).catch((error) => {
    throw humanIpcError(error, document.documentElement.lang);
  });
}

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
  getOpenAtLogin: () => invoke(IPC.invoke.getOpenAtLogin),
  setOpenAtLogin: (enabled) => invoke(IPC.invoke.setOpenAtLogin, enabled),
  recordingPermissions: {
    getStatus: (kind) => invoke(IPC.invoke.recordingStatus, kind),
    request: (kind) => invoke(IPC.invoke.recordingRequest, kind),
    openSettings: (kind) => invoke(IPC.invoke.recordingOpenSettings, kind),
  },
  data: {
    exportDiagnostics: () => invoke(IPC.invoke.dataExportDiagnostics),
    createBackup: (token) => invoke(IPC.invoke.dataCreateBackup, { token }),
    applyRestore: (stageId) => invoke(IPC.invoke.dataApplyRestore, { stageId }),
  },
  // 更新:checkUpdates 主动查(设置页按钮);onUpdateAvailable 订阅启动静默检查的结果。
  checkUpdates: () => invoke(IPC.invoke.checkUpdates),
  // 开发时主进程过期:哪几份产物变了、能不能重启;变了推一次;要求重启(见 main.cjs 的 restartMain)。
  devMain: {
    status: () => invoke(IPC.invoke.mainStatus),
    onStale: (callback) => onEvent(IPC.event.mainStale, callback),
    restart: () => invoke(IPC.invoke.restartMain),
  },
  onUpdateAvailable: (callback) => onEvent(IPC.event.updateAvailable, callback),
  // 全屏状态订阅:主进程在进入/退出全屏(及首帧)推送布尔值。订阅时立即补发缓存的当前值,
  // 避免渲染层挂载晚于首帧推送时"有时"漏掉全屏态。
  // 自定义 CSS(userData/custom.css)。read 取当前内容,onChange 订阅存盘后的推送 ——
  // 「改一下就生效」靠的是后者,而不是让渲染层去轮询文件。
  customCss: {
    read: () => invoke(IPC.invoke.customCssRead),
    path: () => invoke(IPC.invoke.customCssPath),
    open: () => invoke(IPC.invoke.customCssOpen),
    reveal: () => invoke(IPC.invoke.customCssReveal),
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
  login: (accountId, platform) => invoke(IPC.invoke.publishLogin, { accountId, platform }),
  openPage: (accountId, platform) => invoke(IPC.invoke.publishOpenPage, { accountId, platform }),
  signOut: (accountId, platform) => invoke(IPC.invoke.publishSignOut, { accountId, platform }),
  inspect: (accountId, platform) => invoke(IPC.invoke.publishInspect, { accountId, platform }),
  navigate: (url) => invoke(IPC.invoke.publishNavigate, { url }),
  back: () => invoke(IPC.invoke.publishBack),
  forward: () => invoke(IPC.invoke.publishForward),
  reload: () => invoke(IPC.invoke.publishReload),
  hideView: () => invoke(IPC.invoke.publishHideView),
  onViewState: (callback) => onEvent(IPC.event.publishView, callback),
  /** 悬浮卡片几何(见 main.cjs onPanels):渲染层照它画圆角/阴影/标题条。 */
  /** 拖动/缩放悬浮面板(几何由主进程持有并落盘)。 */
  setPanelLayout: (patch) => invoke(IPC.invoke.publishPanelLayout, patch),
  /** 手动关闭某块面板:只撤面板,任务照常继续。 */
  closePanel: (id) => invoke(IPC.invoke.publishClosePanel, { id }),
  /** 悬浮浏览器声音开关；真实状态随 onPanels 回传。 */
  setPanelMuted: (id, muted) => invoke(IPC.invoke.publishPanelMuted, { id, muted }),
  onPanels: (callback) => onEvent(IPC.event.publishPanels, callback),
  // 前台会话的页面列表(左侧那一列):页面本身随 onViewState 的 pages 下发。
  switchPage: (id) => invoke(IPC.invoke.publishSwitchPage, { id }),
  closePage: (id) => invoke(IPC.invoke.publishClosePage, { id }),
  reorderPages: (ids) => invoke(IPC.invoke.publishReorderPages, { ids }),
  newPage: (url) => invoke(IPC.invoke.publishNewPage, { url }),
  setPagesInset: (left) => invoke(IPC.invoke.publishPagesInset, { left }),
  snapshotPage: () => invoke(IPC.invoke.publishSnapshotPage),
  coverPage: (covered) => invoke(IPC.invoke.publishCoverPage, { covered }),
  focusPage: () => invoke(IPC.invoke.publishFocusPage),
  // 外壳里的悬停说明画到网页上面(浮层视图):不等回话,跟着说明出、收。
  showFloat: (hint) => ipcRenderer.send(IPC.send.floatShow, hint),
  hideFloat: (id) => ipcRenderer.send(IPC.send.floatHide, id ? { id } : {}),
};
contextBridge.exposeInMainWorld("mosaelPublish", publishBridge);

// 自动化浏览器(RPA / 智能体)的实时预览帧:离屏视图截帧,前端画成缩略预览。
/** @type {import("./preload-api").MosaelBrowserBridge} */
const browserBridge = {
  onFrame: (callback) => onEvent(IPC.event.browserFrame, callback),
  // 通用池档案登录:在该档案分区开内嵌视图登任意站点(见 main.cjs browser:openLogin)。
  openLogin: (opts) => invoke(IPC.invoke.browserOpenLogin, opts),
  clearProfile: (partition) => invoke(IPC.invoke.browserClearProfile, { partition }),
  // 工作流库「在编辑器里打开」(见 main.cjs comfyui:openWorkflow)。
  openComfyWorkflow: (opts) => invoke(IPC.invoke.comfyuiOpenWorkflow, opts),
  // 工作流库「新建」(见 main.cjs comfyui:newWorkflow)。
  newComfyWorkflow: (opts) => invoke(IPC.invoke.comfyuiNewWorkflow, opts),
  // 内嵌 ComfyUI 画布的操控方式(见 main.cjs comfyui:navigation)。
  setComfyNavigation: (opts) => invoke(IPC.invoke.comfyuiNavigation, opts),
  // ComfyUI 工作台(见 main.cjs comfyui:openWorkbench / workbenchCall / closeWorkbench,事件 comfyui:workbench)。
  openComfyWorkbench: (opts) => invoke(IPC.invoke.comfyuiOpenWorkbench, opts),
  comfyWorkbench: (opts) => invoke(IPC.invoke.comfyuiWorkbenchCall, opts),
  onComfyWorkbench: (callback) => onEvent(IPC.event.comfyuiWorkbench, callback),
};
contextBridge.exposeInMainWorld("mosaelBrowser", browserBridge);

// 浏览器会话顶栏的页面工具。都作用于前台那个内嵌视图 —— 渲染层不点名要哪个视图(见 publish/pageTarget.ts)。
/** @type {import("./preload-api").MosaelPageToolsBridge} */
const pageToolsBridge = {
  capture: (mode) => invoke(IPC.invoke.pageToolsCapture, { mode }),
  beginRegion: () => invoke(IPC.invoke.pageToolsRegionStart),
  finishRegion: (selection) => invoke(IPC.invoke.pageToolsRegionFinish, { selection }),
  probeVideos: () => invoke(IPC.invoke.pageToolsVideos),
  listImages: () => invoke(IPC.invoke.pageToolsImages),
  fetchImages: (urls) => invoke(IPC.invoke.pageToolsFetchImages, { urls }),
  readPage: (mode) => invoke(IPC.invoke.pageToolsRead, { mode }),
  setInset: (right) => invoke(IPC.invoke.pageToolsInset, { right }),
  // 内嵌浏览器里点的下载不弹保存框:主进程报进度 / 下好了,渲染层带着自己的会话来存进素材库。
  onDownload: (callback) => onEvent(IPC.event.pageToolsDownload, callback),
  saveDownload: (request) => invoke(IPC.invoke.pageToolsSaveDownload, request),
};
contextBridge.exposeInMainWorld("mosaelPageTools", pageToolsBridge);
