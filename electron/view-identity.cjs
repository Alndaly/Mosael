// 内嵌浏览器对外声明的身份 —— **按平台**决定,不再是全局一种。
//
// 两套反欺诈对这个客户端的期待正好相反(2026-10-22 的现场):
//
// - **微信视频号**:浏览器身份一改成「如实声明 Electron」,快捷登录就登不上 —— 客户端点了 Allow、
//   页面也确实登进去了,可随即又退回登录页(维护者:改动指纹之前是正常的)。它要的是浏览器形状的身份。
// - **X / Cloudflare Turnstile**:抹成 Chrome 形状反而被针对性挑战(help.x.com 上无限循环验证),
//   如实声明的 Electron UA 才过。
//
// 所以身份跟着**平台**走:默认给干净 Chrome UA(抹掉 `Electron/x.y.z` 与应用名 token,其它一个字不改),
// X 单独保持如实声明。指纹那几处(preload 里的 webdriver/chrome/languages/plugins)两边一致,不动 ——
// 之前的教训是**假指纹**才是破绽,UA 只是门牌。
//: 哪些平台**不**洗 UA(如实声明 Electron)。
//:
//: **判据不是「哪家反欺诈更凶」,而是「洗了之后 UA 和 client hints 还一致吗」**。我们只洗 UA 字符串,
//: 洗不动 Chromium 自己报的 `navigator.userAgentData` / `Sec-CH-UA`(那要 CDP 的
//: Emulation.setUserAgentOverride,而它会让 Cloudflare Turnstile 判定为「自称 Chrome、信号不像」)。
//: 于是洗过的 UA 变成**自相矛盾**的一份身份:UA 说 Chrome/152,hints 说 Chromium 且没有 Google Chrome
//: 品牌 —— 视频号 2026-10-22 实测:扫码/快捷登录都成功种下了 sessionid,随后立刻被判无效、退回登录页。
//:
//: 所以默认**如实声明**(自洽);哪天真要 Chrome 形状的身份,得三处一起对齐(CDP),不能只洗 UA。
//: X 早就是这一档(Turnstile 的实测结论),视频号在排查「扫码后回登录页」时也归到这一档。
//:
//: **小红书也先归到这一档(2026-10-23 实验)**:它的发布风控会在点「发布」时要求扫码/身份验证,
//: 而「自称 Chrome、信号不像」正是那类风控最容易抓的一组证据。改回如实声明之后要复核两件事:
//: ① 登录还进得去 ② 发布是否不再弹验证。不行就把这一项删掉 —— 一行的事。
//:
//: **YouTube 也回到这一档(2026-10-23)**:维护者说「以前我是可以的」—— 对的,10-22 那批身份改动
//: 之前 YouTube 用的是如实声明的 Electron,登录能过;改成「干净 Chrome UA + CDP 对齐」之后,
//: Google 在输完密码那一刻回 `accounts.google.com/v3/signin/rejected`「此浏览器或应用可能不安全」。
//: 而 CDP 对齐那条路要在建视图时**挂上 debugger**,那本身就是 DevTools 特征。先回退到能用的那一档。
const CHROME_IDENTITY_EXEMPT = new Set(["x", "twitter", "xiaohongshu", "youtube"]);

/** 抹掉 UA 里的 Electron 与 Mosael token,得到一枚干净 Chrome UA;认不出 Chrome 版本就原样返回。 */
function cleanChromeUserAgent(userAgent) {
  const ua = String(userAgent || "");
  if (!/Chrome\/[0-9]/.test(ua)) return ua;
  return ua
    .replace(/\sElectron\/[0-9][^\s]*/g, "")
    .replace(/\sMosael\/[0-9][^\s]*/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** macOS 的产品版本 = Darwin 主版本 - 9(Chromium 在 client hints 里报的是产品版本,不是内核版本)。 */
function macPlatformVersion(systemVersion, platform) {
  if (platform !== "darwin") return "";
  const [major = 0, minor = 0] = String(systemVersion || "")
    .split(".")
    .map((one) => Number.parseInt(one, 10) || 0);
  return major >= 20 ? `${major - 9}.${minor}.0` : "10.15.7";
}

/**
 * 一枚**自洽**的 Chrome 身份,交给 CDP 的 `Emulation.setUserAgentOverride`。
 *
 * 为什么非它不可:抹 UA 字符串只改 UA,Chromium 自己报的 client hints(`Sec-CH-UA` 头与
 * `navigator.userAgentData`)还是「Chromium + Not_A Brand」——**没有 Google Chrome 品牌**。
 * 这就成了「自称 Chrome、信号不像」。视频号 2026-10-22 实测:扫码/快捷登录都成功、`sessionid`
 * 也确实种进了分区,平台页随即判会话无效、退回登录页。
 *
 * `Emulation.setUserAgentOverride` 是 Chromium 给 Puppeteer / DevTools 做同样事情的那条路:
 * 它一次覆盖 UA 请求头、client hints 头与 `navigator.userAgentData`,三处说的是同一件事。
 * (webContents 的 `setUserAgent` 只覆盖 UA 字符串 —— 那条路试过,修不了。)
 */
function chromeIdentityOverride(userAgent, options = {}) {
  const version = /Chrome\/(\d+)\.(\d+)\.(\d+)\.(\d+)/.exec(String(userAgent || ""));
  if (!version) return null;
  const [, major, minor, build, patch] = version;
  const full = `${major}.${minor}.${build}.${patch}`;
  const platform = options.platform || "darwin";
  const arch = options.arch || "arm64";
  const mac = platform === "darwin";
  return {
    userAgent: String(userAgent),
    acceptLanguage: "zh-CN,zh;q=0.9,en;q=0.8",
    platform: mac ? "MacIntel" : platform === "win32" ? "Win32" : "Linux x86_64",
    userAgentMetadata: {
      brands: [
        { brand: "Google Chrome", version: major },
        { brand: "Chromium", version: major },
        { brand: "Not_A Brand", version: "24" },
      ],
      fullVersionList: [
        { brand: "Google Chrome", version: full },
        { brand: "Chromium", version: full },
        { brand: "Not_A Brand", version: "24.0.0.0" },
      ],
      fullVersion: full,
      platform: mac ? "macOS" : platform === "win32" ? "Windows" : "Linux",
      platformVersion: macPlatformVersion(options.systemVersion, platform),
      architecture: arch === "arm64" ? "arm" : "x86",
      model: "",
      mobile: false,
      bitness: "64",
    },
  };
}

/** 这个平台用哪一档身份:`"chrome"`(干净 Chrome UA)或 `"electron"`(如实声明,不洗)。 */
function identityForPlatform(platform) {
  const id = String(platform || "").trim().toLowerCase();
  return CHROME_IDENTITY_EXEMPT.has(id) ? "electron" : "chrome";
}

module.exports = { CHROME_IDENTITY_EXEMPT, chromeIdentityOverride, cleanChromeUserAgent, identityForPlatform };
