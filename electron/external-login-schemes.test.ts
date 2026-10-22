/**
 * 登录要唤起本机客户端的那几种协议(微信快捷登录的 `weixin://`)。
 *
 * 现场:视频号创作页点「微信快捷登录」没反应、又回到登录页 —— 不是指纹问题,是 Chromium 不认识这个
 * 协议、静默丢掉了。这里钉两件事:白名单只认这几种(页面不可信,不能让网页指挥系统开任意程序),
 * 以及它会真的交给系统、并且拦下页面自己的导航。
 */
import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs / accountViews 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { forwardExternalLogin, isExternalLoginUrl, LOGIN_SCHEMES } = require("./external-login-schemes.cjs") as {
  forwardExternalLogin: (
    contents: { on: (name: string, listener: (event: unknown, url?: string) => void) => void },
    openExternal: (url: string) => Promise<void> | void,
  ) => unknown;
  isExternalLoginUrl: (url: string) => boolean;
  LOGIN_SCHEMES: Set<string>;
};

function fakeContents() {
  const listeners = new Map<string, (event: unknown, url?: string) => void>();
  return {
    listeners,
    on: (name: string, listener: (event: unknown, url?: string) => void) => listeners.set(name, listener),
  };
}

function fakeEvent(url?: string) {
  return { url, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
}

describe("登录协议的转发", () => {
  it("只认唤起本机客户端的那几种;http(s)、file、javascript 一律不碰", () => {
    expect(isExternalLoginUrl("weixin://dl/login?token=abc")).toBe(true);
    expect(isExternalLoginUrl("weixinmac://x")).toBe(true);
    expect(isExternalLoginUrl("wxwork://x")).toBe(true);
    for (const url of ["https://channels.weixin.qq.com/login.html", "file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", "not a url"]) {
      expect(isExternalLoginUrl(url), url).toBe(false);
    }
    expect([...LOGIN_SCHEMES]).not.toContain("file");
  });

  it("点到登录协议:拦下页面自己的导航,交给系统去唤起客户端", async () => {
    const contents = fakeContents();
    const opened: string[] = [];
    forwardExternalLogin(contents, (url) => { opened.push(url); });

    const event = fakeEvent();
    contents.listeners.get("will-navigate")!(event, "weixin://dl/login?token=abc");
    expect(event.defaultPrevented).toBe(true);
    expect(opened).toEqual(["weixin://dl/login?token=abc"]);

    // 子框架发起的也算(qrconnect 的 iframe 里就是)
    const frameEvent = fakeEvent("weixin://dl/login?token=zzz");
    contents.listeners.get("will-frame-navigate")!(frameEvent);
    expect(frameEvent.defaultPrevented).toBe(true);
    expect(opened).toHaveLength(2);
  });

  it("普通网页导航不受影响(不拦、不唤起任何东西)", () => {
    const contents = fakeContents();
    const opened: string[] = [];
    forwardExternalLogin(contents, (url) => { opened.push(url); });

    const event = fakeEvent();
    contents.listeners.get("will-navigate")!(event, "https://channels.weixin.qq.com/platform");
    expect(event.defaultPrevented).toBe(false);
    expect(opened).toEqual([]);
  });
});
