/**
 * 身份按平台走:默认干净 Chrome UA,X 保持如实声明。
 *
 * 这条规则来自两次真机回归:视频号在「如实声明 Electron」之后登不上(Allow 完又退登录页);
 * 而 X / Turnstile 在 Chrome 伪装下无限循环。同一台内嵌浏览器不可能同时满足两边。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: main.cjs 的视图层加载同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { cleanChromeUserAgent, identityForPlatform, chromeIdentityOverride } = require("./view-identity.cjs") as {
  cleanChromeUserAgent: (ua: string) => string;
  identityForPlatform: (platform: string | null | undefined) => "chrome" | "electron";
  chromeIdentityOverride: (
    ua: string,
    options?: { platform?: string; arch?: string; systemVersion?: string },
  ) => { userAgent: string; acceptLanguage: string; platform: string; userAgentMetadata: Record<string, unknown> } | null;
};

const ELECTRON_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.7977.130 Electron/44.4.5 Safari/537.36";

describe("内嵌浏览器的身份", () => {
  it("抹掉 Electron 与应用名 token,别的原样保留", () => {
    expect(cleanChromeUserAgent(ELECTRON_UA)).toBe(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.7977.130 Safari/537.36",
    );
    expect(cleanChromeUserAgent(ELECTRON_UA.replace("Electron/44.4.5", "Electron/44.4.5 Mosael/2.0.1"))).not.toContain("Mosael");
    // 认不出 Chrome 版本(比如已经是干净 UA 或奇怪字符串)就原样返回,不猜。
    const clean = "Mozilla/5.0 (X11; Linux x86_64) Chrome/152.0.0.0 Safari/537.36";
    expect(cleanChromeUserAgent(clean)).toBe(clean);
    expect(cleanChromeUserAgent("curl/8")).toBe("curl/8");
    expect(cleanChromeUserAgent("")).toBe("");
  });

  it("X 如实声明;其余平台(视频号、抖音、小红书…)给**对齐过 client hints** 的 Chrome 身份", () => {
    for (const platform of ["x", "X", "twitter"]) expect(identityForPlatform(platform), platform).toBe("electron");
    for (const platform of ["weixin-channels", "douyin", "xiaohongshu", "bilibili", "tiktok", "youtube"]) {
      expect(identityForPlatform(platform), platform).toBe("chrome");
    }
    // 未知 / 空:默认干净 Chrome(登录能过的那一边),不是永久伪装。
    expect(identityForPlatform(null)).toBe("chrome");
    expect(identityForPlatform("")).toBe("chrome");
  });

  it("CDP 那份覆盖:UA 与 client hints 说的是同一件事(有 Google Chrome 品牌)", () => {
    const clean = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.7977.130 Safari/537.36";
    const override = chromeIdentityOverride(clean, { platform: "darwin", arch: "arm64", systemVersion: "25.0.0" })!;
    expect(override.userAgent).toBe(clean);
    const metadata = override.userAgentMetadata as { brands: Array<{ brand: string }>; platformVersion: string; architecture: string };
    //: 这就是视频号那轮缺的东西:UA 说 Chrome,而 brands 里只有 Chromium。
    expect(metadata.brands.map((one) => one.brand)).toContain("Google Chrome");
    expect(metadata.platformVersion).toBe("16.0.0");
    expect(metadata.architecture).toBe("arm");
    // 认不出 Chrome 版本就返回 null(调用方退回只洗 UA),不编一个身份。
    expect(chromeIdentityOverride("curl/8")).toBeNull();
  });
});
