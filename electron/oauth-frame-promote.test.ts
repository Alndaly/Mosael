/**
 * 第三方登录回调落在 iframe 里时,提到顶层(视频号快捷登录的现场)。
 *
 * 现场:微信客户端点了「Allow」之后,`open.weixin.qq.com` 那个跨站 iframe 自己导航到
 * `channels.weixin.qq.com/platform/oauth-callback.html?code=…`,而**跨站 iframe 里种不下会话 cookie**
 * —— 平台页随后一调接口就说未登录,又跳回登录页。把这一步挪到顶层就是第一方上下文。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: accountViews 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { registrableDomain, shouldPromoteFrameNavigation } = require("./oauth-frame-promote.cjs") as {
  registrableDomain: (hostname: string) => string;
  shouldPromoteFrameNavigation: (frameUrl: string, topUrl: string) => boolean;
};

describe("登录回调的 iframe → 顶层", () => {
  it("视频号那一例:回调地址与顶层同域,提上来", () => {
    expect(
      shouldPromoteFrameNavigation(
        "https://channels.weixin.qq.com/platform/oauth-callback.html?code=abc&state=x",
        "https://channels.weixin.qq.com/login.html",
      ),
    ).toBe(true);
  });

  it("别的子框架跳转一律不动:广告、播放器、跨域回调、普通页内跳转", () => {
    const top = "https://channels.weixin.qq.com/login.html";
    expect(shouldPromoteFrameNavigation("https://ads.example.com/code=1", top)).toBe(false);
    expect(shouldPromoteFrameNavigation("https://channels.weixin.qq.com/platform/home", top)).toBe(false);
    // 跨注册域的回调也不提(那是另一家的流程,提上来只会把用户带出这一页)
    expect(
      shouldPromoteFrameNavigation("https://other.example.com/oauth/callback?code=1", top),
    ).toBe(false);
    expect(shouldPromoteFrameNavigation("about:blank", top)).toBe(false);
    expect(shouldPromoteFrameNavigation("not a url", top)).toBe(false);
  });

  it("**发起**登录那一步不提上来 —— 它的 redirect_uri 参数里写着 callback,但那不是回调", () => {
    //: 现场:第一版按「地址里出现 oauth-callback」判,于是把 qrconnect 自己提到了顶层,
    //: 用户看到的是一个没有站点外框、只有一个「微信快捷登录」按钮的裸页。
    expect(
      shouldPromoteFrameNavigation(
        "https://open.weixin.qq.com/connect/qrconnect?appid=wx20d84d087938fd46&scope=snsapi_login" +
          "&redirect_uri=https%3A%2F%2Fchannels.weixin.qq.com%2Fplatform%2Foauth-callback.html%3Fdark%3D1" +
          "&state=undefined&login_type=jssdk&self_redirect=true",
        "https://channels.weixin.qq.com/login.html",
      ),
    ).toBe(false);
    expect(shouldPromoteFrameNavigation("https://channels.weixin.qq.com/platform/login?next=1", "https://channels.weixin.qq.com/login.html")).toBe(false);
  });

  it("注册域:同域不同子域算一个,两级后缀(co.uk / com.cn)多留一段", () => {
    //: 注册域是「可注册后缀 + 一段」:weixin.qq.com 的注册域就是 qq.com(和浏览器给 cookie 定作用域同一档)。
    expect(registrableDomain("channels.weixin.qq.com")).toBe("qq.com");
    expect(registrableDomain("open.weixin.qq.com")).toBe("qq.com");
    expect(registrableDomain("a.b.example.co.uk")).toBe("example.co.uk");
    expect(registrableDomain("x.example.com.cn")).toBe("example.com.cn");
    expect(registrableDomain("localhost")).toBe("localhost");
    expect(registrableDomain("127.0.0.1")).toBe("127.0.0.1");
  });
});
