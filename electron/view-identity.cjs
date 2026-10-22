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
const CHROME_IDENTITY_EXEMPT = new Set(["x", "twitter"]);

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
