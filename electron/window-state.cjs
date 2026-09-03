"use strict";

/**
 * 把 BrowserWindow 的全屏生命周期映射成渲染层可直接消费的布尔状态。
 *
 * enter/leave 事件本身才是真值。不要在事件回调里重新读取 isFullScreen():macOS 的窗口转换
 * 跨越原生事件循环,退出事件到达时读取值仍可能是 true,从而让渲染层一直误以为处于全屏。
 */
function bindFullscreenState(win, channel) {
  const publish = (fullscreen) => {
    if (!win.isDestroyed()) win.webContents.send(channel, Boolean(fullscreen));
  };

  win.on("enter-full-screen", () => publish(true));
  win.on("leave-full-screen", () => publish(false));
  win.webContents.on("did-finish-load", () => publish(win.isFullScreen()));
}

module.exports = { bindFullscreenState };
