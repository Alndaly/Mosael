/**
 * 身份按平台走:默认干净 Chrome UA,X 保持如实声明。
 *
 * 这条规则来自两次真机回归:视频号在「如实声明 Electron」之后登不上(Allow 完又退登录页);
 * 而 X / Turnstile 在 Chrome 伪装下无限循环。同一台内嵌浏览器不可能同时满足两边。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: main.cjs 的视图层加载同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { cleanChromeUserAgent, identityForPlatform } = require("./view-identity.cjs") as {
  cleanChromeUserAgent: (ua: string) => string;
  identityForPlatform: (platform: string | null | undefined) => "chrome" | "electron";
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

  it("X 与视频号如实声明(洗 UA 会和 client hints 自相矛盾);其余平台给干净 Chrome UA", () => {
    for (const platform of ["x", "X", "twitter", "weixin-channels"]) {
      expect(identityForPlatform(platform), platform).toBe("electron");
    }
    for (const platform of ["douyin", "xiaohongshu", "bilibili", "tiktok", "youtube"]) {
      expect(identityForPlatform(platform), platform).toBe("chrome");
    }
    // 未知 / 空:默认干净 Chrome(登录能过的那一边),不是永久伪装。
    expect(identityForPlatform(null)).toBe("chrome");
    expect(identityForPlatform("")).toBe("chrome");
  });
});
