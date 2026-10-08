"use strict";

/**
 * 主窗口的渲染进程崩了之后怎么办。
 *
 * 此前什么都不做:内存撑爆(大工程剪辑)、GPU 重置之后窗口就是一块灰,多数人不知道按 ⌘R;内嵌浏览器亮着时 ⌘R 刷的还是
 * 网页,Mosael 那一圈一直是死的。现在自动重新载入(内嵌视图的状态在 did-finish-load 时补播,工作台视图由
 * releaseWorkbenchView 收起);一分钟里连崩三次就不再自己重来 —— 那多半是一载入就崩,再载也是一样 —— 停下来问人。
 *
 * 规则和后端崩溃重启用同一个退避(backend-lifecycle 的 createRestartPolicy),只是窗口更短、更快。
 */
const { createRestartPolicy } = require("./backend-lifecycle.cjs");

/**
 * @param {{
 *   reload: () => void,
 *   giveUp: (details: { reason: string, exitCode?: number }) => void,
 *   schedule?: (callback: () => void, ms: number) => unknown,
 *   policy?: ReturnType<typeof createRestartPolicy>,
 *   log?: (line: string) => void,
 * }} options
 * @returns {(details: { reason: string, exitCode?: number }) => void}  挂到 render-process-gone 上
 */
function createRendererRecovery({
  reload,
  giveUp,
  schedule = (callback, ms) => setTimeout(callback, ms),
  policy = createRestartPolicy({ maxRestarts: 3, windowMs: 60_000, baseDelayMs: 500 }),
  log = () => undefined,
}) {
  return (details) => {
    // 正常退出(窗口关了、应用在退)不是崩溃。
    if (!details || details.reason === "clean-exit") return;
    const delay = policy.next();
    if (delay === null) {
      log(`renderer keeps crashing (${details.reason}); asking`);
      giveUp(details);
      return;
    }
    log(`renderer gone (${details.reason}); reloading in ${delay}ms`);
    schedule(reload, delay);
  };
}

module.exports = { createRendererRecovery };
