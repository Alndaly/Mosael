import { app } from "electron";


/**
 * 开机自启。
 *
 * 和 residency 是一对:关窗不退让 App 在开机之后一直活着,开机自启让它在开机之后**先**活起来。
 * 少了任何一半,「每天 9 点自动发布」都还是要用户记得手动开一次 App。
 *
 * 自启时带 --hidden:直接静默驻留托盘,而不是每次开机弹一个窗口出来。Windows/Linux 靠这个
 * 命令行参数;mac 从登录项拉起时系统不传参数,改问 `wasOpenedAtLogin`(见 isHiddenLaunch)。
 */

const HIDDEN_FLAG = "--hidden";

export function isHiddenLaunch(): boolean {
  if (process.argv.includes(HIDDEN_FLAG)) return true;
  // mac:从「登录项」拉起时系统不会传我们的参数,得问它。
  //
  // 问的是 `wasOpenedAtLogin`(系统在登录时自动拉起了我),不是已经删掉的 `wasOpenedAsHidden`。
  // Electron 44 把后者连同 `openAsHidden` 一起移除了 —— 它们只在 macOS 12 及以下有效,
  // 而 12 已不在支持范围内。留着的话读回来是 undefined,`=== true` 恒为 false:
  // 开机静默启动从此永远检测不到,而且一声不吭。
  //
  // 换成 wasOpenedAtLogin 不是找个字段顶上,而是**判据本来就该是这个**:我们注册登录项的
  // 目的就是静默驻留托盘,所以「被登录拉起」和「该静默」在这个应用里是同一件事。
  try {
    return app.getLoginItemSettings().wasOpenedAtLogin === true;
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
    // **读的时候必须带上和写时同样的 args。** Electron 文档原话:「If you provided `path`
    // and `args` options to `app.setLoginItemSettings`, then you need to pass the same
    // arguments here for `openAtLogin` to be set correctly.」
    //
    // 我们写的时候带了 `--hidden`(自启时静默驻留托盘),而这里此前不带 —— 于是 Windows 上
    // `openAtLogin` 永远读回 false。注册表其实已经写进去了、开机真的会自启,而界面把开关
    // 弹了回去。真机反馈的「开机时启动点击无效」就是这么来的:功能生效了,界面在说谎。
    const settings = app.getLoginItemSettings({ args: [HIDDEN_FLAG] });

    // Windows 专有的两个字段是更结实的判据:
    //   executableWillLaunchAtLogin —— **忽略 args**,只问"这个可执行文件会不会开机启动";
    //   launchItems[].enabled —— 注册表项在,但用户在任务管理器/设置里把它关掉了。
    // 后者正是 Windows 版的「登记了、还没生效」,和 macOS 的 requires-approval 是一回事。
    const willLaunch = (settings as { executableWillLaunchAtLogin?: boolean }).executableWillLaunchAtLogin === true;
    const items = (settings as { launchItems?: { enabled?: boolean }[] }).launchItems ?? [];
    const deactivated = items.length > 0 && items.every((item) => item.enabled === false);

    const needsApproval =
      (settings as { status?: string }).status === "requires-approval" || (willLaunch && deactivated);
    // 登记上了就把开关显示成开 —— 「还差你去批准/启用」不是「没开成」。
    return { enabled: settings.openAtLogin === true || willLaunch || needsApproval, needsApproval };
  } catch {
    return { enabled: false, needsApproval: false };
  }
}

export function getOpenAtLogin(): LoginItemState {
  return readState();
}

export function setOpenAtLogin(enabled: boolean): LoginItemState {
  // 不再传 openAsHidden:Electron 44 移除了它(只在 macOS 12 及以下有效)。静默这件事现在
  // 两边都靠 --hidden 参数 + 上面 isHiddenLaunch 里的 wasOpenedAtLogin 兜住。
  app.setLoginItemSettings({
    openAtLogin: enabled,
    args: enabled ? [HIDDEN_FLAG] : [],
  });
  return readState();
}

// 注:这里没有导出 Capability。开机自启不需要在启动时"注册"任何东西,它只是三个按需调用的
// 函数;硬凑一个空的 register 只会让注册表里多一条什么都不做的记录。
//
// 开发模式必须由宿主(main.cjs)挡住不要暴露这几个函数:此时 process.execPath 是 Electron
// 二进制本身,写进系统登录项等于让用户开机启动一个裸 Electron,而且清理要手动去系统设置里翻。
