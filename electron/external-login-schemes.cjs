// 内嵌浏览器里「登录要拉起本机客户端」的那几种协议。
//
// 现场(2026-10-22,微信视频号):创作页的「微信快捷登录」是 `weixin://…` —— 点它等于让**操作系统**
// 去唤起微信 PC 端,微信弹一个确认,页面那边的轮询拿到票据才算登录完成。Chromium 默认不认这个协议,
// 于是这一下被静默丢掉:用户看到的是「点了没反应 / 又回到登录页」,而页面的指纹、UA、cookie 都正常。
//
// 所以这里只做一件事:**把真正是「唤起本机客户端」的那几种 scheme 交给系统**。白名单**故意很短** ——
// 页面内容是不可信的,放开任意 scheme 等于让一个网页指挥操作系统去打开任意程序。`file:` / `data:` /
// `javascript:` / 别的自定义协议一律不在这里,仍然按「不认」处理。
const LOGIN_SCHEMES = new Set(["weixin", "weixinmac", "wxwork", "wecom"]);

/** 这个地址是不是「要唤起本机客户端才能完成登录」的那一种。 */
function isExternalLoginUrl(url) {
  try {
    return LOGIN_SCHEMES.has(new URL(String(url)).protocol.replace(/:$/, "").toLowerCase());
  } catch {
    return false;
  }
}

/**
 * 给一个 webContents 接上:遇到登录协议就交给系统,其余不管(导航该拦的由调用方自己拦)。
 * `openExternal` 由调用方注入 —— 测试里给替身,主进程里是 `shell.openExternal`。
 */
function forwardExternalLogin(contents, openExternal) {
  const forward = (event, url) => {
    if (!isExternalLoginUrl(url)) return false;
    event?.preventDefault?.();
    Promise.resolve(openExternal(String(url))).catch(() => undefined);
    return true;
  };
  contents.on("will-navigate", (event, url) => forward(event, url));
  // 子框架也可能发起它(qrconnect 的 iframe 里就是),所以两条都接。
  contents.on("will-frame-navigate", (event) => forward(event, event?.url));
  return forward;
}

module.exports = { forwardExternalLogin, isExternalLoginUrl, LOGIN_SCHEMES };
