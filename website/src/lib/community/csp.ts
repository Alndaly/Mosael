/**
 * 分享画板查看页(`/{locale}/b/{slug}`)的内容安全策略(ADR 0026 §6「分享查看页有严格的 CSP」)。
 *
 * 画板上的一切都是别人上传的:图片、视频、文档正文。这一页的 CSP 按「页面上有攻击者可控的内容」来写:
 *
 * - 脚本只认本次请求的 nonce(Next 会把它打到自己的脚本上)+ `strict-dynamic`,不认任何内联脚本、
 *   不认别的域名;没有 `unsafe-eval`(开发模式例外,React 的调试要它)。
 * - 媒体只从本站和部署时配置的存储域名(`COMMUNITY_MEDIA_ORIGINS`,S3 / COS 那种不同源的存储)来。
 * - 不许被别的站嵌进 iframe,不许 `<object>`,`<base>` 不许改,表单只能提交回本站。
 * - 样式放行内联:React Flow 与 Radix 用 style 属性定位,属性上的样式没法挂 nonce。
 *
 * 代价:站点根布局里的主题脚本(next-themes)与统计脚本拿不到 nonce,在这一页不执行 —— 主题在水合之后
 * 由 next-themes 补上,统计在这一页不采集。换来的是用户上传的东西在这一页上什么脚本也跑不起来。
 */

/** `COMMUNITY_MEDIA_ORIGINS`:空格或逗号分隔的 origin 列表。只收 https(开发时也收 http)的纯 origin。 */
export function mediaOrigins(raw: string | undefined, dev = false): string[] {
  if (!raw) return [];
  const origins: string[] = [];
  for (const one of raw.split(/[\s,]+/)) {
    if (!one) continue;
    try {
      const url = new URL(one);
      if (url.protocol === "https:" || (dev && url.protocol === "http:")) origins.push(url.origin);
    } catch {
      // 写错的项跳过:宁可少放行一个域名,也不让一串非法值进 CSP。
    }
  }
  return [...new Set(origins)];
}

export function shareCsp({ nonce, media, dev }: { nonce: string; media: string[]; dev: boolean }): string {
  const extra = media.length > 0 ? ` ${media.join(" ")}` : "";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob:${extra}`,
    `media-src 'self' blob:${extra}`,
    "font-src 'self' data:",
    `connect-src 'self'${dev ? " ws: wss:" : ""}`,
    "frame-src 'none'",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  if (!dev) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}
