// Computer Use 的「屏幕四角描边」(ADR 0075 安全 2):每个显示器一块透明、不接鼠标、不抢焦点的窗口。
//
// 放在单独的文件里而不是 main.cjs:主进程那个文件已经很长,而这几块窗口的生命周期(创建 / 显示 /
// 收掉 / 显示器变化)是**一块能单独看的东西**;electron 依赖由调用方传进来,测试里可以替身。
//
// 它只画,不判断:什么时候亮、什么时候灭由 computerUseGuard.cjs 的状态说了算。

/**
 * 只画一圈红边。**不再写「正在操作」那句话** —— 窗口里那条提示条已经把同一件事说了,还带着
 * 「停止」按钮;两边各说一遍就是同一语义画了两遍(维护者反复提的那条)。
 */
function computerUseOverlayHtml() {
  return `<!doctype html><html><body style="margin:0;background:transparent;overflow:hidden">
  <div style="position:fixed;inset:0;border:3px solid rgba(239,68,68,0.92);border-radius:16px;box-sizing:border-box"></div>
  </body></html>`;
}

function createComputerUseOverlay(options = {}) {
  const BrowserWindow = options.BrowserWindow;
  const screen = options.screen;
  let windows = [];

  function show() {
    if (!BrowserWindow || !screen || windows.length > 0) return;
    for (const display of screen.getAllDisplays()) {
      const overlay = new BrowserWindow({
        x: display.bounds.x,
        y: display.bounds.y,
        width: display.bounds.width,
        height: display.bounds.height,
        frame: false,
        transparent: true,
        hasShadow: false,
        resizable: false,
        movable: false,
        minimizable: false,
        maximizable: false,
        fullscreenable: false,
        skipTaskbar: true,
        focusable: false,
        show: false,
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
      });
      overlay.setIgnoreMouseEvents(true);
      overlay.setAlwaysOnTop(true, "screen-saver");
      void overlay.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(computerUseOverlayHtml())}`);
      overlay.once("ready-to-show", () => overlay.showInactive());
      windows.push(overlay);
    }
  }

  function hide() {
    for (const overlay of windows) {
      try {
        overlay.destroy();
      } catch {
        /* 已经没了 */
      }
    }
    windows = [];
  }

  return { show, hide, count: () => windows.length };
}

module.exports = { createComputerUseOverlay, computerUseOverlayHtml };
