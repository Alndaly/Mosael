// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.mibuPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");

// 桌面环境标识:前端据此加 is-desktop / is-mac 类,适配无边框窗(红绿灯占位、拖拽区)。
// setTitleOverlay:Win/Linux 的标题栏三键叠层颜色随主题切换(mac 无此叠层,调用为 no-op)。
contextBridge.exposeInMainWorld("mibuDesktop", {
  platform: process.platform,
  setTitleOverlay: (colors) => ipcRenderer.send("mibu:title-overlay", colors),
  // 全屏状态订阅:主进程在进入/退出全屏(及首帧)推送布尔值。
  onFullscreen: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("mibu:fullscreen", listener);
    return () => ipcRenderer.removeListener("mibu:fullscreen", listener);
  },
});

contextBridge.exposeInMainWorld("mibuPublish", {
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
});
