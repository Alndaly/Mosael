import { app } from "electron";

import type { Capability, SystemContext } from "./types";

/**
 * 常驻:关窗 = 收进托盘,不退出。
 *
 * 这是定时任务能力的地基。后端是主进程 spawn 的子进程,退出时 before-quit 会把它 SIGTERM
 * 掉(见 main.cjs 的 stopBackend)——也就是说**关掉 App 等于调度循环也停了**,定时任务到点
 * 什么都不会发生,下次开 App 才靠 next_run_at 过期补跑一次。用户按「每天 9 点发布」配好
 * 之后关掉窗口,以为它会跑,其实不会。
 *
 * 在此之前 Windows/Linux 上关窗直接 app.quit()(window-all-closed 里 platform !== "darwin"),
 * mac 上则是关窗留着进程但没有任何可见入口——两种都不好。统一成:关窗只是隐藏,托盘是
 * 唯一的可见留存标志,退出走托盘菜单或 ⌘Q/菜单栏。
 */

/** 真正要退出了(托盘菜单退出 / ⌘Q / 系统关机),此时 close 不再拦截。 */
let quitting = false;

export function isQuitting(): boolean {
  return quitting;
}

/** 供宿主在 before-quit 里调用。 */
export function markQuitting(): void {
  quitting = true;
}

export const residency: Capability = {
  name: "residency",
  register(ctx: SystemContext) {
    const onBeforeQuit = () => {
      quitting = true;
    };
    app.on("before-quit", onBeforeQuit);

    // 窗口关闭 → 拦下来改成隐藏。注意要 preventDefault 而不是 e.returnValue,
    // 后者在 Electron 的 close 事件上无效。
    const attach = () => {
      const win = ctx.getWindow();
      if (!win || win.isDestroyed()) return;
      win.on("close", (event) => {
        if (quitting) return;
        event.preventDefault();
        win.hide();
        // mac:同时从 Dock 隐藏会让人以为退出了,所以保留 Dock 图标,只藏窗口。
      });
    };
    attach();

    return {
      dispose: () => {
        app.off("before-quit", onBeforeQuit);
      },
    };
  },
};
