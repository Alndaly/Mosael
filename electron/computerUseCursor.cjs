// Computer Use 的「指针提示」(ADR 0075 安全 2 的延伸):动手时在**窗口里那个点**上画一枚指针,
// 让「它刚才点了哪里」看得见 —— 否则被自动放行连点几下,人只看到界面莫名变化。
//
// 一块很小的透明窗口(不接鼠标、不抢焦点、不进任务栏),位置跟着每一次点击 / 滚动走;一次动作
// 亮一下,`HOLD_MS` 之后自己收起来。它是**提示**,不是真光标:窗口不属于页面,`capturePage()`
// 拍不到它 —— 模型看到的那张图里不会多出一枚假指针。
//
// 坐标换算是调用方的事(主进程知道窗口在屏幕上的位置);这里只负责「在屏幕的某个点上亮一下」。

const CURSOR_HTML = `<!doctype html><html><body style="margin:0;background:transparent;overflow:hidden">
<style>
  #ripple{position:absolute;left:2px;top:2px;width:32px;height:32px;border-radius:999px;
    border:2px solid rgba(239,68,68,.95);opacity:0;pointer-events:none}
  @keyframes cue{from{transform:scale(.25);opacity:.95}to{transform:scale(1.5);opacity:0}}
</style>
<svg width="26" height="26" viewBox="0 0 26 26" style="position:absolute;left:2px;top:2px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.35))">
  <path d="M3 1.5 L3 20.5 L8.2 15.9 L11.4 23 L14.4 21.7 L11.2 14.8 L18 14.8 Z"
        fill="#ffffff" stroke="#111111" stroke-width="1.5" stroke-linejoin="round"/>
</svg>
<div id="ripple"></div>
<script>
  window.cue = function () {
    var r = document.getElementById('ripple');
    r.style.animation = 'none';
    void r.offsetWidth;  /* 重新触发动画 */
    r.style.animation = 'cue .85s ease-out 1';
  };
</script>
</body></html>`;

/**
 * @param {object} options
 * @param {new (options: object) => any} options.BrowserWindow Electron 的 BrowserWindow(测试里给替身)
 * @param {number} [options.size] 提示窗口的边长
 * @param {number} [options.holdMs] 一次动作亮多久
 * @param {Function} [options.setTimer]/[options.clearTimer] 定时器(测试注入)
 */
function createComputerUseCursor(options = {}) {
  const BrowserWindow = options.BrowserWindow;
  const size = Number.isInteger(options.size) && options.size > 0 ? options.size : 44;
  const holdMs = Number.isInteger(options.holdMs) && options.holdMs > 0 ? options.holdMs : 1600;
  const setTimer = typeof options.setTimer === "function" ? options.setTimer : setTimeout;
  const clearTimer = typeof options.clearTimer === "function" ? options.clearTimer : clearTimeout;
  let win = null;
  let timer = null;

  const ensure = () => {
    if (win && (typeof win.isDestroyed !== "function" || !win.isDestroyed())) return win;
    if (!BrowserWindow) return null;
    win = new BrowserWindow({
      width: size,
      height: size,
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
    win.setIgnoreMouseEvents(true);
    win.setAlwaysOnTop(true, "screen-saver");
    void win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(CURSOR_HTML)}`);
    return win;
  };

  /** 在屏幕坐标 (x, y) 上亮一下:指针的**尖端**落在那个点(窗口左上角因此偏移半个窗口)。 */
  function showAt(x, y, kind = "click") {
    const target = ensure();
    if (!target) return false;
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
    const left = Math.round(Number(x) - 4);
    const top = Math.round(Number(y) - 4);
    try {
      target.setPosition(left, top);
      target.showInactive();
      // 每个动作都重新触发那一圈涟漪;页面还没加载完就安静地跳过(下一次动作会再来)。
      const script = `window.cue && window.cue(${JSON.stringify(String(kind))})`;
      if (typeof target.webContents?.executeJavaScript === "function") {
        void target.webContents.executeJavaScript(script).catch(() => undefined);
      }
    } catch {
      return false;
    }
    timer = setTimer(() => {
      timer = null;
      hide();
    }, holdMs);
    if (timer && typeof timer.unref === "function") timer.unref();
    return true;
  }

  function hide() {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
    if (!win) return;
    try {
      if (!win.isDestroyed()) win.hide();
    } catch {
      /* 已经没了 */
    }
  }

  function dispose() {
    hide();
    try {
      if (win && !win.isDestroyed()) win.destroy();
    } catch {
      /* 已经没了 */
    }
    win = null;
  }

  return { showAt, hide, dispose };
}

module.exports = { createComputerUseCursor, CURSOR_HTML };
