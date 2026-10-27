// 登录排障:把**某个站点**的请求结果记进结构化日志(P7 的延伸)。
//
// 现场(2026-10-22 视频号):扫码/快捷登录都能完成,`sessionid` 也确实种进了分区,但页面随后又回到
// 登录页。页面自己的判定写在 `login.html` 的请求拦截器里 ——「`sessionid` 读不到就 `location.href =
// login.html`」;再外面是平台页的会话校验。光看 cookie 表看不出是哪一条请求把它判死的,只能看**请求**。
//
// 规矩与 trace 一致:只记 origin+path(查询串整体抹掉 —— 里面可能有 code / ticket),不记 cookie。
const DEFAULT_HOSTS = ["channels.weixin.qq.com", "open.weixin.qq.com"];

/** 只把这些站点的请求交给 `read`(其余原样返回 null)。 */
function makeFilter(hosts = DEFAULT_HOSTS) {
  const wanted = new Set(hosts);
  return (rawUrl) => {
    try {
      const url = new URL(String(rawUrl));
      return wanted.has(url.hostname) ? url : null;
    } catch {
      return null;
    }
  };
}

/**
 * 挂到一个 session 上。`seen` 是 WeakSet(同一个 session 只挂一次 —— 每建一个 tab 都会走到这里)。
 * 回调只拿到已经抹干净的 path 与状态码。
 */
function watchSession(session, onEvent, options = {}) {
  const filter = makeFilter(options.hosts);
  const seen = options.seen || new WeakSet();
  if (!session || !session.webRequest) return;
  if (seen.has(session)) return;
  seen.add(session);
  const relay = (kind) => (details) => {
    const url = filter(details.url);
    if (!url) return;
    onEvent({
      kind,
      method: details.method || "",
      path: url.pathname,
      status: details.statusCode ?? details.error ?? "",
      resource: details.resourceType || "",
    });
  };
  const patterns = (options.hosts || DEFAULT_HOSTS).map((host) => `*://${host}/*`);
  try {
    session.webRequest.onCompleted({ urls: patterns }, relay("done"));
    session.webRequest.onErrorOccurred({ urls: patterns }, relay("error"));
    //: 302 才是登录流程的常态:回调 → 平台页 → 又回登录页。链子上每一跳都要看得见。
    session.webRequest.onBeforeRedirect({ urls: patterns }, (details) => {
      const url = filter(details.url);
      if (!url) return;
      onEvent({
        kind: "redirect",
        method: details.method || "",
        path: url.pathname,
        status: details.statusCode ?? "",
        resource: details.resourceType || "",
      });
    });
  } catch {
    /* 旧版 Electron 没有 onErrorOccurred 之类:排障设施,失败不影响业务 */
  }
}

module.exports = { DEFAULT_HOSTS, makeFilter, watchSession };
