/**
 * 读登录项状态时**必须带上写时那组 args**。
 *
 * Electron 文档原话:「If you provided `path` and `args` options to
 * `app.setLoginItemSettings`, then you need to pass the same arguments here for
 * `openAtLogin` to be set correctly.」
 *
 * 我们写的时候带了 `--hidden`(自启时静默驻留托盘),而读的时候此前不带 —— 于是 Windows 上
 * `openAtLogin` 永远读回 false。注册表其实已经写进去、开机真的会自启,而界面把开关弹回去。
 * 真机反馈的「开机时启动点击无效」就是这么来的:**功能生效了,界面在说谎**。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  getSpy: vi.fn(),
  setSpy: vi.fn(),
}));

vi.mock("electron", () => ({
  app: {
    getLoginItemSettings: h.getSpy,
    setLoginItemSettings: h.setSpy,
  },
}));

const { getOpenAtLogin, setOpenAtLogin } = await import("./loginItem");

beforeEach(() => {
  h.getSpy.mockReset();
  h.setSpy.mockReset();
});

describe("开机自启的状态", () => {
  it("读的时候带上了写时那组 args", () => {
    h.getSpy.mockReturnValue({ openAtLogin: true });
    getOpenAtLogin();
    expect(h.getSpy).toHaveBeenCalledWith({ args: ["--hidden"] });
  });

  it("写完之后回读用的也是同一组 args —— 否则刚写完就读成没写", () => {
    h.getSpy.mockReturnValue({ openAtLogin: true });
    const state = setOpenAtLogin(true);
    expect(h.setSpy).toHaveBeenCalledWith(
      expect.objectContaining({ openAtLogin: true, args: ["--hidden"] }),
    );
    expect(h.getSpy).toHaveBeenCalledWith({ args: ["--hidden"] });
    expect(state.enabled).toBe(true);
  });

  it("Windows:openAtLogin 读不出来,但可执行文件确实会自启 —— 算开着", () => {
    // executableWillLaunchAtLogin 忽略 args,是更结实的判据。
    h.getSpy.mockReturnValue({ openAtLogin: false, executableWillLaunchAtLogin: true, launchItems: [{ enabled: true }] });
    expect(getOpenAtLogin()).toEqual({ enabled: true, needsApproval: false });
  });

  it("Windows:注册表项在、但被用户在任务管理器里关掉了 —— 是「还差一步」,不是「没开成」", () => {
    h.getSpy.mockReturnValue({
      openAtLogin: false,
      executableWillLaunchAtLogin: true,
      launchItems: [{ enabled: false }],
    });
    expect(getOpenAtLogin()).toEqual({ enabled: true, needsApproval: true });
  });

  it("macOS:等系统设置里批准 —— 同样是「还差一步」", () => {
    h.getSpy.mockReturnValue({ openAtLogin: false, status: "requires-approval" });
    expect(getOpenAtLogin()).toEqual({ enabled: true, needsApproval: true });
  });

  it("真的没开就是没开", () => {
    h.getSpy.mockReturnValue({ openAtLogin: false, status: "not-registered", launchItems: [] });
    expect(getOpenAtLogin()).toEqual({ enabled: false, needsApproval: false });
  });

  it("读不出来时不假装知道", () => {
    h.getSpy.mockImplementation(() => { throw new Error("nope"); });
    expect(getOpenAtLogin()).toEqual({ enabled: false, needsApproval: false });
  });
});
