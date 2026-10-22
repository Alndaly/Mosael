// 第三方登录回调落在 **iframe 里**时,把它提到顶层再打开。
//
// 现场(2026-10-22,微信视频号快捷登录):登录页把二维码/快捷登录放在
// `open.weixin.qq.com/connect/qrconnect?...&self_redirect=true` 这个**跨站 iframe** 里;微信客户端点了
// 「Allow」之后,iframe 自己会导航到 `redirect_uri`(channels.weixin.qq.com/platform/oauth-callback.html
// ?code=…),由那一页把会话 cookie 种下来。问题就在这一步:**跨站 iframe 里种的 cookie 受第三方规则
// 约束**(SameSite / 存储分区),于是 cookie 要么没存下、要么随后的请求不带它 —— 平台页一调接口就说
// 「未登录」,于是**又跳回登录页**。用户看到的是「同意之后登录成功,然后立刻退回登录」。
//
// 修法是把这一步挪到**顶层**:同一个地址在主框架打开时是**第一方**上下文,cookie 正常种下、正常随请求
// 发送。判据刻意很窄 —— 只有「子框架 + 地址带 OAuth 回调标记 + 和顶层页面同一个注册域」这一种才提上来,
// 别的一律不碰(广告 iframe、内嵌播放器、第三方统计都不受影响)。

/** 地址里出现这些,才认为它是「登录回调」而不是普通子页面跳转。 */
const CALLBACK_MARKERS = /(?:[?&#](?:code|state|auth_code|ticket|login_ticket)=)|oauth[-_]?callback|\/oauth\//i;

/** 注册域:比 hostname 粗一档(`a.b.com` 与 `c.b.com` 同域)。IP 与 localhost 原样返回。 */
function registrableDomain(hostname) {
  const host = String(hostname || "").toLowerCase();
  if (!host || host.startsWith("[") || /^\d+\.\d+\.\d+\.\d+$/.test(host) || host === "localhost") return host;
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  //: 两级后缀(co.uk / com.cn / com.hk …)多留一段。
  const twoLevel = /^(?:co|com|net|org|gov|edu|ac)\.[a-z]{2}$/.test(parts.slice(-2).join("."));
  return parts.slice(twoLevel ? -3 : -2).join(".");
}

/**
 * 这个子框架导航要不要提到顶层。`frameUrl` 是子框架要去的地址,`topUrl` 是这一页此刻的顶层地址。
 */
function shouldPromoteFrameNavigation(frameUrl, topUrl) {
  let frame;
  let top;
  try {
    frame = new URL(String(frameUrl));
    top = new URL(String(topUrl || ""));
  } catch {
    return false;
  }
  if (frame.protocol !== "https:" && frame.protocol !== "http:") return false;
  if (!CALLBACK_MARKERS.test(frame.href)) return false;
  const frameDomain = registrableDomain(frame.hostname);
  const topDomain = registrableDomain(top.hostname);
  return Boolean(frameDomain) && frameDomain === topDomain;
}

module.exports = { registrableDomain, shouldPromoteFrameNavigation };
