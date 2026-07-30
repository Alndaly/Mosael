// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.openStudioPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");

// 全屏状态在渲染层挂载 React 监听器之前就可能推来(主进程 did-finish-load 时发一帧),
// 那一帧会错过 → 全屏时左上角边距"有时"没撤。这里在 preload 加载即订阅并缓存最新值,
// onFullscreen 订阅时先补发缓存,消除时序竞态。
let lastFullscreen = false;
ipcRenderer.on("openstudio:fullscreen", (_event, value) => {
  lastFullscreen = Boolean(value);
});

// 桌面环境标识:前端据此加 is-desktop / is-mac 类,适配无边框窗(红绿灯占位、拖拽区)。
// setTitleOverlay:Win/Linux 的标题栏三键叠层颜色随主题切换(mac 无此叠层,调用为 no-op)。
contextBridge.exposeInMainWorld("openStudioDesktop", {
  platform: process.platform,
  setTitleOverlay: (colors) => ipcRenderer.send("openstudio:title-overlay", colors),
  // 更新:checkUpdates 主动查(设置页按钮);onUpdateAvailable 订阅启动静默检查的结果。
  checkUpdates: () => ipcRenderer.invoke("openstudio:check-updates"),
  onUpdateAvailable: (callback) => {
    const listener = (_event, info) => callback(info);
    ipcRenderer.on("openstudio:update-available", listener);
    return () => ipcRenderer.removeListener("openstudio:update-available", listener);
  },
  // 全屏状态订阅:主进程在进入/退出全屏(及首帧)推送布尔值。订阅时立即补发缓存的当前值,
  // 避免渲染层挂载晚于首帧推送时"有时"漏掉全屏态。
  onFullscreen: (callback) => {
    callback(lastFullscreen);
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("openstudio:fullscreen", listener);
    return () => ipcRenderer.removeListener("openstudio:fullscreen", listener);
  },
});

contextBridge.exposeInMainWorld("openStudioPublish", {
  login: (accountId, platform) => ipcRenderer.invoke("publish:login", { accountId, platform }),
  openPage: (accountId, platform) => ipcRenderer.invoke("publish:openPage", { accountId, platform }),
  inspect: (accountId, platform) => ipcRenderer.invoke("publish:inspect", { accountId, platform }),
  navigate: (url) => ipcRenderer.invoke("publish:navigate", { url }),
  back: () => ipcRenderer.invoke("publish:back"),
  forward: () => ipcRenderer.invoke("publish:forward"),
  reload: () => ipcRenderer.invoke("publish:reload"),
  hideView: () => ipcRenderer.invoke("publish:hideView"),
  onViewState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("publish:view", listener);
    return () => ipcRenderer.removeListener("publish:view", listener);
  },
  /** 悬浮卡片几何(见 main.cjs onPanels):渲染层照它画圆角/阴影/标题条。 */
  /** 拖动/缩放悬浮面板(几何由主进程持有并落盘)。 */
  setPanelLayout: (patch) => ipcRenderer.invoke("publish:panelLayout", patch),
  /** 手动关闭某块面板:只撤面板,任务照常继续。 */
  closePanel: (id) => ipcRenderer.invoke("publish:closePanel", { id }),
  onPanels: (callback) => {
    const listener = (_event, cards) => callback(cards);
    ipcRenderer.on("publish:panels", listener);
    return () => ipcRenderer.removeListener("publish:panels", listener);
  },
});

// 自动化浏览器(RPA / 智能体)的实时预览帧:离屏视图截帧,前端画成缩略预览。
contextBridge.exposeInMainWorld("openStudioBrowser", {
  onFrame: (callback) => {
    const listener = (_event, frame) => callback(frame);
    ipcRenderer.on("browser:frame", listener);
    return () => ipcRenderer.removeListener("browser:frame", listener);
  },
  // 通用池档案登录:在该档案分区开内嵌视图登任意站点(见 main.cjs browser:openLogin)。
  openLogin: (opts) => ipcRenderer.invoke("browser:openLogin", opts),
});
