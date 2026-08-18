import { app } from "electron";


/**
 * 开机自启。
 *
 * 和 residency 是一对:关窗不退让 App 在开机之后一直活着,开机自启让它在开机之后**先**活起来。
 * 少了任何一半,「每天 9 点自动发布」都还是要用户记得手动开一次 App。
 *
 * 自启时带 --hidden:直接静默驻留托盘,而不是每次开机弹一个窗口出来。mac 有原生的
 * openAsHidden 表达同一件事,Windows/Linux 只能靠命令行参数,所以两边都给。
 */

const HIDDEN_FLAG = "--hidden";

export function isHiddenLaunch(): boolean {
  if (process.argv.includes(HIDDEN_FLAG)) return true;
  // mac:从「登录项」拉起时系统不会传我们的参数,得问它。
  try {
    return app.getLoginItemSettings().wasOpenedAsHidden === true;
  } catch {
    return false;
  }
}

/**
 * 登录项此刻的状态。
 *
 * **不是一个 boolean。** macOS 13 起这件事走 SMAppService:写进去之后系统可能把它挂成
 * 「等用户批准」(系统设置 → 通用 → 登录项),而在批准之前 `openAtLogin` 仍然是 false。
 * 只回一个 boolean 的话,界面拿到 false 就把开关弹回去 —— 用户点了、系统里确实多了一条待批准
 * 的记录,而界面说什么都没发生。真机反馈就是「开机时启动点击无效」。
 *
 * 「要你去批准」和「没开成」是两件事,得分开说。
 */
export type LoginItemState = {
  /** 系统里这一项现在真的生效了没有。 */
  enabled: boolean;
  /** macOS:注册上了,但**还等用户在系统设置里点允许**。 */
  needsApproval: boolean;
};

function readState(): LoginItemState {
  try {
    const settings = app.getLoginItemSettings();
    // status 只有 macOS 给;别的平台按 openAtLogin 判断就够了。
    const needsApproval = (settings as { status?: string }).status === "requires-approval";
    return { enabled: settings.openAtLogin === true || needsApproval, needsApproval };
  } catch {
    return { enabled: false, needsApproval: false };
  }
}

export function getOpenAtLogin(): LoginItemState {
  return readState();
}

export function setOpenAtLogin(enabled: boolean): LoginItemState {
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: enabled,
    args: enabled ? [HIDDEN_FLAG] : [],
  });
  return readState();
}

// 注:这里没有导出 Capability。开机自启不需要在启动时"注册"任何东西,它只是三个按需调用的
// 函数;硬凑一个空的 register 只会让注册表里多一条什么都不做的记录。
//
// 开发模式必须由宿主(main.cjs)挡住不要暴露这几个函数:此时 process.execPath 是 Electron
// 二进制本身,写进系统登录项等于让用户开机启动一个裸 Electron,而且清理要手动去系统设置里翻。
