/**
 * 「这个账号登上了吗」——发布器判定登录态的那条规则。
 *
 * 被测的是 Electron 主进程里的适配器。放在这里是因为仓库只有这一套 vitest(与
 * deepLinkParse.test.ts 同因),逻辑归属仍是 electron/publish/adapters.ts。
 *
 * ## 为什么值得单独测
 *
 * 登录轮询(publishWorker.openLogin)每 5 秒问一次 `checkLogin()`,而它**不能导航**——用户正在
 * 那个页面上敲密码。也就是说:判定必须在「用户此刻恰好停在哪一页」都成立。
 *
 * 线上翻车过一次:YouTube 走完 Google 登录会跳到 `www.youtube.com`(看视频那个站,不是 Studio),
 * 那里既没有文件输入也没有任何 Studio 字样,于是**明明登上了,账号池一直显示「登录已失效」**。
 * 修法是加一条与页面无关的判据(分区里的会话 cookie),这几条用例把它钉住。
 *
 * 另一半同样重要:cookie 只能做**正向**信号。会话过期时平台会把人重定向回登录页,那一条必须
 * 先命中——否则残留 cookie 会把已经失效的会话说成有效,任务照发不误,然后在上传那一步才炸。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// log.ts 会 `import { app } from "electron"` 落盘日志;这里只测判定逻辑,给个最小替身。
vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

import type { PageDriver } from "../../../electron/publish/pageDriver";

// 动态 import:vi.mock("electron") 必须在模块求值前生效。
const { TiktokAdapter, YoutubeAdapter } = await import("../../../electron/publish/adapters");

interface FakePage {
  url: string;
  /** 分区里存着的 cookie 名(模拟 Electron session,与当前页面无关)。 */
  cookies?: string[];
  /** 页面上能找到的文案(创作页标志 / 登录页标志)。 */
  texts?: string[];
  /** 页面上有没有文件输入(创作页的上传入口)。 */
  fileInput?: boolean;
  /** 匹配得上的 CSS(TikTok 用 data-e2e 标记判登录页)。 */
  css?: string[];
}

/** 只实现 checkLogin 会用到的那几个原语;其余一律不该被调用。 */
function fakeDriver(page: FakePage) {
  const calls: string[] = [];
  const driver = {
    url: () => page.url,
    hasCookie: async (_url: string, names: readonly string[]) => {
      calls.push("hasCookie");
      return (page.cookies ?? []).some((name) => names.includes(name));
    },
    fileInputAttached: async () => {
      calls.push("fileInputAttached");
      return page.fileInput === true;
    },
    cssAttached: async (selector: string) => (page.css ?? []).includes(selector),
    hasTextDeep: async (text: string) => (page.texts ?? []).includes(text),
  };
  return { driver: driver as unknown as PageDriver, calls };
}

const task = { platformOptions: {} } as never;

describe("YouTube 登录态判定", () => {
  beforeEach(() => vi.clearAllMocks());

  it("**登完停在 www.youtube.com 也要认得出来** —— 那里没有任何 Studio 标志", async () => {
    // 线上真实现场:用户已登录、内嵌浏览器停在 youtube.com,账号池却报「登录已失效」。
    const { driver } = fakeDriver({ url: "https://www.youtube.com/", cookies: ["SAPISID"] });
    expect(await new YoutubeAdapter(driver, task).checkLogin()).toBe(true);
  });

  it("在 Studio 上传页上,按页面判据认(不依赖 cookie)", async () => {
    const { driver } = fakeDriver({ url: "https://www.youtube.com/upload", fileInput: true });
    expect(await new YoutubeAdapter(driver, task).checkLogin()).toBe(true);
  });

  it("**被重定向到 Google 登录页 = 未登录,残留 cookie 不能翻案**", async () => {
    // 会话过期正是这个形状:cookie 还躺在分区里,但服务端已经不认了。
    const { driver } = fakeDriver({
      url: "https://accounts.google.com/ServiceLogin?service=youtube",
      cookies: ["SAPISID", "__Secure-3PAPISID"],
    });
    expect(await new YoutubeAdapter(driver, task).checkLogin()).toBe(false);
  });

  it("既没有会话 cookie 也没有创作页标志 —— 判未登录,不许兜底成已登录", async () => {
    const { driver } = fakeDriver({ url: "https://www.youtube.com/" });
    expect(await new YoutubeAdapter(driver, task).checkLogin()).toBe(false);
  });

  it("cookie 命中就不必再等 8 秒的文件输入探测", async () => {
    // 轮询每 5 秒一轮,而 fileInputAttached 要等满 8 秒;顺序错了会让每一轮都白等。
    const { driver, calls } = fakeDriver({ url: "https://www.youtube.com/", cookies: ["SAPISID"] });
    await new YoutubeAdapter(driver, task).checkLogin();
    expect(calls).toEqual(["hasCookie"]);
  });
});

describe("TikTok 登录态判定", () => {
  it("登完停在 www.tiktok.com 信息流也要认得出来", async () => {
    const { driver } = fakeDriver({ url: "https://www.tiktok.com/foryou", cookies: ["sessionid"] });
    expect(await new TiktokAdapter(driver).checkLogin()).toBe(true);
  });

  it("**在登录页就是未登录**,残留 cookie 不能翻案", async () => {
    const { driver } = fakeDriver({ url: "https://www.tiktok.com/login", cookies: ["sessionid"] });
    expect(await new TiktokAdapter(driver).checkLogin()).toBe(false);
  });

  it("页面上挂着登录页的 data-e2e 标记时,同样判未登录", async () => {
    const { driver } = fakeDriver({
      url: "https://www.tiktok.com/tiktokstudio/upload",
      cookies: ["sessionid"],
      css: ['[data-e2e="login-title"], [data-e2e="channel-item"]'],
    });
    expect(await new TiktokAdapter(driver).checkLogin()).toBe(false);
  });

  it("没 cookie 没标志 —— 判未登录", async () => {
    const { driver } = fakeDriver({ url: "https://www.tiktok.com/foryou" });
    expect(await new TiktokAdapter(driver).checkLogin()).toBe(false);
  });
});
