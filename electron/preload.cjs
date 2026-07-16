// 渲染层桥:发布执行器(主进程)API + 内嵌视图状态事件。
// contextIsolation 下渲染层通过 window.mibuPublish 使用;非 Electron 环境该对象不存在,
// 前端以此判断「桌面发布器是否可用」。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mibuPublish", {
  login: (accountId, platform) => ipcRenderer.invoke("publish:login", { accountId, platform }),
  openPage: (accountId, platform) => ipcRenderer.invoke("publish:openPage", { accountId, platform }),
  hideView: () => ipcRenderer.invoke("publish:hideView"),
  onViewState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("publish:view", listener);
    return () => ipcRenderer.removeListener("publish:view", listener);
  },
});
