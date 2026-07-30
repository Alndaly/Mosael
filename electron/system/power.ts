import { powerMonitor, powerSaveBlocker } from "electron";

import type { Capability, SystemStatus } from "./types";

/**
 * 有任务在跑时阻止系统睡眠。
 *
 * 渲染、发布、声音克隆下载都是分钟到小时级,而这些活干到一半机器合盖睡了,ffmpeg /
 * 下载进程会被一起挂起 —— 醒来后任务看着还在「运行中」,实际已经停了很久,严重时超时判失败。
 *
 * 用 prevent-app-suspension 而不是 prevent-display-sleep:我们要的是系统别睡,屏幕该黑就黑。
 * 后者会把用户的屏幕一直点着,对一个后台渲染任务来说是过度索取。
 *
 * 注:powerMonitor 在这里只用来记日志。定时任务不需要它兜底——调度循环每 5 秒 tick 一次,
 * 醒来后自然会看到过期的 next_run_at;而 compute_next_run_at 是从当前时间重算的,
 * 所以睡了 8 小时也只补跑一次,不会堆积成一串。
 */

export const power: Capability = {
  name: "power",
  register() {
    let blockerId: number | null = null;

    const release = () => {
      if (blockerId === null) return;
      try {
        if (powerSaveBlocker.isStarted(blockerId)) powerSaveBlocker.stop(blockerId);
      } catch {
        /* 已经停了 */
      }
      blockerId = null;
    };

    const onSuspend = () => {
      console.warn("[system] 系统进入睡眠;运行中的任务可能被挂起");
    };
    const onResume = () => {
      console.info("[system] 系统已唤醒");
    };
    powerMonitor.on("suspend", onSuspend);
    powerMonitor.on("resume", onResume);

    return {
      onStatus: (status: SystemStatus) => {
        if (status.runningJobs > 0) {
          if (blockerId === null) blockerId = powerSaveBlocker.start("prevent-app-suspension");
        } else {
          release();
        }
      },
      dispose: () => {
        powerMonitor.off("suspend", onSuspend);
        powerMonitor.off("resume", onResume);
        release();
      },
    };
  },
};
