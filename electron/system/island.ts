import path from "node:path";

import { IPC } from "../ipc-contract.cjs";
import { createMacosIsland } from "../macos-island.cjs";
import type { Capability, SystemContext } from "./types";

/**
 * macOS 灵动岛:一个独立的 borderless NSPanel 进程,不属于 Mosael 的主窗口。
 *
 * 这条能力只做三件事:
 * - 找到随包分发的 helper;
 * - 把渲染层推来的 `liveActivities` 写给它;
 * - 用户点岛上某一件时,把主窗口叫出来并把 id 交回渲染层。
 *
 * helper 缺失、平台不是 macOS、进程崩了都不影响应用 —— 托盘、通知、任务中心照旧。
 */
function helperPath(ctx: SystemContext): string {
  return ctx.isDev
    ? path.join(__dirname, "..", "build", "macos-island", "mosael-island")
    : path.join(process.resourcesPath, "macos-island", "mosael-island");
}

export const island: Capability = {
  name: "island",
  register(ctx: SystemContext) {
    if (process.platform !== "darwin") return;
    const helper = createMacosIsland({
      binaryPath: helperPath(ctx),
      onOpen: (id) => {
        ctx.showWindow();
        const win = ctx.getWindow();
        if (win && !win.isDestroyed()) win.webContents.send(IPC.event.liveActivityOpen, { id });
      },
      log: (line) => console.warn("[system] island:", line),
    });
    helper.start();
    return {
      onStatus: (status) => helper.setActivities(status.liveActivities ?? []),
      dispose: () => helper.dispose(),
    };
  },
};
