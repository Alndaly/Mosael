// Computer Use 的「屏幕四角描边」(ADR 0075 安全 2):每个显示器一块透明、不接鼠标、不抢焦点的窗口。
//
// 放在单独的文件里而不是 main.cjs:主进程那个文件已经很长,而这几块窗口的生命周期(创建 / 显示 /
// 收掉 / 显示器变化)是**一块能单独看的东西**;electron 依赖由调用方传进来,测试里可以替身。
//
// 它只画,不判断:什么时候亮、什么时候灭由 computerUseGuard.cjs 的状态说了算。

/**
 * 红边 + 主屏顶部状态胶囊。红边负责“现在被控制中”;胶囊负责切到别的应用时仍看得见
 * “谁在操作、怎么停”。窗口内提示条仍然保留,因为它带可点击的「停止」按钮。
 */
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function computerUseOverlayHtml(options = {}) {
  const settings = typeof options === "string" ? { label: options } : options;
  const label = settings.label ?? "";
  const hint = settings.hint ?? "";
  const status = settings.showStatus && label
    ? `<div style="position:fixed;top:52px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:8px;max-width:min(720px,calc(100vw - 40px));padding:8px 14px;border:1px solid rgba(239,68,68,.55);border-radius:999px;background:rgba(17,20,24,.94);box-shadow:0 10px 30px rgba(0,0,0,.35);color:#f7f8fa;font:12px/1.35 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;pointer-events:none;white-space:nowrap">
      <span style="width:7px;height:7px;flex:none;border-radius:999px;background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.18)"></span>
      <span style="font-weight:600">${escapeHtml(label)}</span>
      ${hint ? `<span style="color:rgba(247,248,250,.58)">${escapeHtml(hint)}</span>` : ""}
    </div>`
    : "";
  return `<!doctype html><html><body style="margin:0;background:transparent;overflow:hidden">
  <div style="position:fixed;inset:0;border:3px solid rgba(239,68,68,0.92);border-radius:16px;box-sizing:border-box"></div>
  ${status}
  </body></html>`;
}

function createComputerUseOverlay(options = {}) {
  const BrowserWindow = options.BrowserWindow;
  const screen = options.screen;
  const getLabel = typeof options.label === "function" ? options.label : () => options.label ?? "";
  const getHint = typeof options.hint === "function" ? options.hint : () => options.hint ?? "";
  let windows = [];

  function show() {
    if (!BrowserWindow || !screen || windows.length > 0) return;
    const displays = screen.getAllDisplays();
    displays.forEach((display, index) => {
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
      const html = computerUseOverlayHtml({
        label: getLabel(),
        hint: getHint(),
        showStatus: index === 0,
      });
      void overlay.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
      overlay.once("ready-to-show", () => overlay.showInactive());
      windows.push(overlay);
    });
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
