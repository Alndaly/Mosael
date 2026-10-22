// Computer Use 的「被控制中」状态与**急停**(ADR 0075 安全 2/3)。
//
// 两层要求:被控制这件事必须**看得见**(屏幕四角描边、菜单栏图标变色、应用内提示条);而且要能**立刻停**,
// 不依赖 App 在前台(全局热键)。这两层都不认识 Electron —— 纯状态机,怎么显示、怎么接热键由 main.cjs 接。
//
// 语义:
//   · 一次动作(noteActivity)= 进入「被控制中」,之后 idleMs 没有新动作就自动退出;
//   · 急停(stop)= **关掉动手能力**:再来的点击 / 输入一律拒绝(见 noteActivity 抛的错),直到用户
//     明确 resume()。急停不是「歇一会儿」,它得一直挡着 —— 用户按它是为了立刻让它停手。
//   · 状态变化通过 onStateChange 推出去(active / stopped / reason),显示层照着画。

function createComputerUseGuard(options = {}) {
  const idleMs = Number.isInteger(options.idleMs) && options.idleMs > 0 ? options.idleMs : 30_000;
  const now = typeof options.now === "function" ? options.now : Date.now;
  const onStateChange = typeof options.onStateChange === "function" ? options.onStateChange : () => {};
  const setTimer = typeof options.setTimeout === "function" ? options.setTimeout : setTimeout;
  const clearTimer = typeof options.clearTimeout === "function" ? options.clearTimeout : clearTimeout;

  let active = false;
  let stopped = false;
  let timer = null;
  let lastActivityAt = 0;

  const state = (reason) => ({ active, stopped, reason, lastActivityAt });

  function disarm() {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }

  function arm() {
    disarm();
    timer = setTimer(() => {
      timer = null;
      if (!active) return;
      active = false;
      onStateChange(state("idle"));
    }, idleMs);
    // 测试里的替身定时器没有 unref;真的 Node 定时器有,别让它拖着进程。
    if (timer && typeof timer.unref === "function") timer.unref();
  }

  /** 一次真的要发生的动作:进入「被控制中」。被急停挡着时**抛错**,调用方什么都不做。 */
  function noteActivity() {
    if (stopped) {
      const error = new Error("Computer Use was stopped by the user. Nothing was done.");
      error.code = "COMPUTER_USE_STOPPED";
      throw error;
    }
    const wasActive = active;
    active = true;
    lastActivityAt = now();
    arm();
    if (!wasActive) onStateChange(state("started"));
  }

  /** 急停:挡住之后所有动作,并让目标状态立刻熄灭。重复按没有副作用。 */
  function stop(reason = "manual") {
    const changed = !stopped;
    stopped = true;
    const wasActive = active;
    active = false;
    disarm();
    if (changed || wasActive) onStateChange(state(reason));
    return changed || wasActive;
  }

  /** 用户明确恢复:允许下一次动作。 */
  function resume() {
    if (!stopped) return false;
    stopped = false;
    onStateChange(state("resumed"));
    return true;
  }

  return {
    noteActivity,
    stop,
    resume,
    isActive: () => active,
    isStopped: () => stopped,
    state: () => state("snapshot"),
    dispose: () => {
      disarm();
      active = false;
      stopped = true;
    },
  };
}

module.exports = { createComputerUseGuard };
