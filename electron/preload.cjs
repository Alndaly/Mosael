// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.mosaelPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");
const { IPC } = require("./ipc-contract.cjs");

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

// 桌面环境标识:前端据此加 is-desktop / is-mac 类,适配无边框窗(红绿灯占位、拖拽区)。
// setTitleOverlay:Win/Linux 的标题栏三键叠层颜色随主题切换(mac 无此叠层,调用为 no-op)。
contextBridge.exposeInMainWorld("mosaelDesktop", {
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
  // 更新:checkUpdates 主动查(设置页按钮);onUpdateAvailable 订阅启动静默检查的结果。
  checkUpdates: () => ipcRenderer.invoke(IPC.invoke.checkUpdates),
  onUpdateAvailable: (callback) => {
    const listener = (_event, info) => callback(info);
    ipcRenderer.on(IPC.event.updateAvailable, listener);
    return () => ipcRenderer.removeListener(IPC.event.updateAvailable, listener);
  },
  // 全屏状态订阅:主进程在进入/退出全屏(及首帧)推送布尔值。订阅时立即补发缓存的当前值,
  // 避免渲染层挂载晚于首帧推送时"有时"漏掉全屏态。
  // 自定义 CSS(userData/custom.css)。read 取当前内容,onChange 订阅存盘后的推送 ——
  // 「改一下就生效」靠的是后者,而不是让渲染层去轮询文件。
  customCss: {
    read: () => ipcRenderer.invoke(IPC.invoke.customCssRead),
    path: () => ipcRenderer.invoke(IPC.invoke.customCssPath),
    open: () => ipcRenderer.invoke(IPC.invoke.customCssOpen),
    reveal: () => ipcRenderer.invoke(IPC.invoke.customCssReveal),
    onChange: (callback) => {
      const listener = (_event, css) => callback(css);
      ipcRenderer.on(IPC.event.customCss, listener);
      return () => ipcRenderer.removeListener(IPC.event.customCss, listener);
    },
  },
  onFullscreen: (callback) => {
    callback(lastFullscreen);
    const listener = (_event, value) => callback(value);
    ipcRenderer.on(IPC.event.fullscreen, listener);
    return () => ipcRenderer.removeListener(IPC.event.fullscreen, listener);
  },
});

contextBridge.exposeInMainWorld("mosaelPublish", {
  login: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishLogin, { accountId, platform }),
  openPage: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishOpenPage, { accountId, platform }),
  inspect: (accountId, platform) => ipcRenderer.invoke(IPC.invoke.publishInspect, { accountId, platform }),
  navigate: (url) => ipcRenderer.invoke(IPC.invoke.publishNavigate, { url }),
  back: () => ipcRenderer.invoke(IPC.invoke.publishBack),
  forward: () => ipcRenderer.invoke(IPC.invoke.publishForward),
  reload: () => ipcRenderer.invoke(IPC.invoke.publishReload),
  hideView: () => ipcRenderer.invoke(IPC.invoke.publishHideView),
  onViewState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on(IPC.event.publishView, listener);
    return () => ipcRenderer.removeListener(IPC.event.publishView, listener);
  },
  /** 悬浮卡片几何(见 main.cjs onPanels):渲染层照它画圆角/阴影/标题条。 */
  /** 拖动/缩放悬浮面板(几何由主进程持有并落盘)。 */
  setPanelLayout: (patch) => ipcRenderer.invoke(IPC.invoke.publishPanelLayout, patch),
  /** 手动关闭某块面板:只撤面板,任务照常继续。 */
  closePanel: (id) => ipcRenderer.invoke(IPC.invoke.publishClosePanel, { id }),
  onPanels: (callback) => {
    const listener = (_event, cards) => callback(cards);
    ipcRenderer.on(IPC.event.publishPanels, listener);
    return () => ipcRenderer.removeListener(IPC.event.publishPanels, listener);
  },
});

// 自动化浏览器(RPA / 智能体)的实时预览帧:离屏视图截帧,前端画成缩略预览。
contextBridge.exposeInMainWorld("mosaelBrowser", {
  onFrame: (callback) => {
    const listener = (_event, frame) => callback(frame);
    ipcRenderer.on(IPC.event.browserFrame, listener);
    return () => ipcRenderer.removeListener(IPC.event.browserFrame, listener);
  },
  // 通用池档案登录:在该档案分区开内嵌视图登任意站点(见 main.cjs browser:openLogin)。
  openLogin: (opts) => ipcRenderer.invoke(IPC.invoke.browserOpenLogin, opts),
});
