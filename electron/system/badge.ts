import { app } from "electron";

import type { Capability, SystemContext, SystemStatus } from "./types";

/**
 * 任务在跑时的系统级可见反馈:mac/Linux 的角标数字,Windows 的任务栏进度条。
 *
 * 解决的是「切走之后完全看不到进度」:渲染、发布、声音克隆下载都是分钟到小时级,以前只能
 * 不停切回窗口看一眼。现在应用图标本身就是进度指示器。
 *
 * Windows 这边只做进度条、不做 overlay 图标:overlay 要一张带数字的位图,而主进程里没有
 * 画布可以现画,做成静态图标又表达不了「几个」——那还不如把真实进度画在任务栏上,它本来
 * 就是 Windows 表达后台工作的标准位置。
 */

/** 进度未知(后端还没报)时用不确定态,而不是假装 0% —— 0% 会看起来像卡住了。 */
const INDETERMINATE = { mode: "indeterminate" as const };

export const badge: Capability = {
  name: "badge",
  register(ctx: SystemContext) {
    const clear = () => {
      try {
        app.setBadgeCount(0);
      } catch {
        /* Windows 上不支持,忽略 */
      }
      const win = ctx.getWindow();
      if (win && !win.isDestroyed()) win.setProgressBar(-1);
    };

    return {
      onStatus: (status: SystemStatus) => {
        const running = status.runningJobs;
        if (running <= 0) {
          clear();
          return;
        }
        // mac / Linux:Dock 或启动器上的数字角标。Windows 上这个调用返回 false,无副作用。
        try {
          app.setBadgeCount(running);
        } catch {
          /* 忽略 */
        }
        const win = ctx.getWindow();
        if (!win || win.isDestroyed()) return;
        const progress = status.progress;
        if (typeof progress === "number" && progress >= 0 && progress <= 1) {
          win.setProgressBar(progress);
        } else {
          win.setProgressBar(2, INDETERMINATE);
        }
      },
      dispose: clear,
    };
  },
};
