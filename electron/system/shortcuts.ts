import { globalShortcut } from "electron";

import type { Capability, SystemContext } from "./types";

/**
 * 全局快捷键:唤出 / 收起主窗口。
 *
 * 只做这一个。全局快捷键是**抢占**的——注册成功就意味着从系统里拿走了这个组合键,别的应用
 * 再也收不到。所以只占一个,而且选一个不常被占用的组合;注册失败(已被别人占了)就安静放弃,
 * 绝不去抢:抢赢了受害的是用户正在用的另一个应用,而他根本不知道是谁干的。
 *
 * 和托盘常驻是一对:窗口收进托盘之后,这是不用去点托盘图标的第二条回来的路。
 */

const TOGGLE_ACCELERATOR = "CommandOrControl+Alt+O";

export const shortcuts: Capability = {
  name: "shortcuts",
  register(ctx: SystemContext) {
    let registered = false;
    try {
      registered = globalShortcut.register(TOGGLE_ACCELERATOR, () => {
        const win = ctx.getWindow();
        // 已经在前台 → 收起来;否则唤出。让同一个键既是「叫出来」也是「收回去」。
        if (win && !win.isDestroyed() && win.isVisible() && win.isFocused()) win.hide();
        else ctx.showWindow();
      });
    } catch (err) {
      console.warn("[system] 全局快捷键注册异常:", err);
    }
    if (!registered) {
      console.info(`[system] 全局快捷键 ${TOGGLE_ACCELERATOR} 已被占用,跳过(不抢占)`);
    }

    return {
      dispose: () => {
        try {
          globalShortcut.unregister(TOGGLE_ACCELERATOR);
        } catch {
          /* 没注册上,忽略 */
        }
      },
    };
  },
};
