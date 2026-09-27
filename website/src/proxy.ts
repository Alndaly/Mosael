import { NextResponse, type NextRequest } from "next/server";

import { mediaOrigins, shareCsp } from "@/lib/community/csp";

/**
 * 只管一件事:给分享画板查看页(`/{locale}/b/{slug}`)加严格的 CSP(规则见 lib/community/csp.ts)。
 *
 * nonce 每个请求一个;Next 从请求头里的 CSP 读出它,打到自己的脚本上(这一页本来就是请求时渲染的)。
 * matcher 只匹配这一条路由 —— 文档、下载这些静态页不经过这里,照旧是纯静态文件。
 */
export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const dev = process.env.NODE_ENV === "development";
  const policy = shareCsp({ nonce, media: mediaOrigins(process.env.COMMUNITY_MEDIA_ORIGINS, dev), dev });

  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  return response;
}

export const config = {
  matcher: [
    {
      source: "/:locale/b/:slug",
      // 预取不渲染页面,不需要 nonce。
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
