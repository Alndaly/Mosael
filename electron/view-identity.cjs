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
const CHROME_IDENTITY_EXEMPT = new Set(["x", "twitter", "weixin-channels"]);

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

/** 这个平台用哪一档身份:`"chrome"`(干净 Chrome UA)或 `"electron"`(如实声明,不洗)。 */
function identityForPlatform(platform) {
  const id = String(platform || "").trim().toLowerCase();
  return CHROME_IDENTITY_EXEMPT.has(id) ? "electron" : "chrome";
}

module.exports = { CHROME_IDENTITY_EXEMPT, cleanChromeUserAgent, identityForPlatform };
