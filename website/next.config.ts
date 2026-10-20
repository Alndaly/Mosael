import type { NextConfig } from "next";

import { DEFAULT_LOCALE } from "./src/i18n/config";

const nextConfig: NextConfig = {
  output: "standalone",
  // TypeScript 7 不再暴露 Next 默认走的那套编译器 API,构建会直接失败并让你退回 TS 6。
  // 这个开关让 Next 改用 `tsc` CLI 去做类型检查 —— 保住"依赖取最新版"的前提,而不是为了
  // 迁就构建流程把语言版本降回去。
  experimental: { useTypeScriptCli: true },
  // 仓库根也有 pnpm-workspace.yaml(Electron 应用那套),Turbopack 会误判根目录。
  // 显式指到这里,免得它去别处找依赖。
  turbopack: { root: import.meta.dirname },

  /**
   * 配图的 URL 上带了个版本号(`?v=…`,见 src/lib/media.ts 的 mediaVersion)。Next 16 默认
   * 拒绝带查询串的本地图片,得在这里显式放行 —— 只放 `/media/**` 这一支,别处照旧。
   */
  images: {
    localPatterns: [{ pathname: "/media/**" }],
  },

  /**
   * 全站路由都在 `[locale]` 段下(见 src/app/[locale]/layout.tsx 的说明),`/` 本身没有页面。
   *
   * 这里不做基于 Accept-Language 的协商:那需要 middleware,而 middleware 会让每个请求都
   * 过一次边缘函数,还会让站点没法纯静态导出。英文是默认语言,中文用户在站头一键就能切,
   * 且切换会记在 URL 里 —— 分享出去的链接自带语言,比嗅探来得可预期。
   */
  async redirects() {
    return [
      { source: "/", destination: `/${DEFAULT_LOCALE}`, permanent: false },
      // 四个对象存储插件合成了一个随应用内置的「对象存储」。老版本插件清单里的文档链接、外面贴过的地址
      // 还指着各自的页面 —— 转到合并后的那一页,而不是 404。
      ...["aliyun-oss", "aws-s3", "tencent-cos", "volcengine-tos"].map((slug) => ({
        source: `/:locale/plugins/${slug}`,
        destination: "/:locale/plugins/object-storage",
        permanent: true,
      })),
    ];
  },

  /**
   * MosaelCloud 与官网同源。浏览器只请求 `/api/cloud/v1/*`,这里把它转给 Cloud 服务:
   * 本地开发默认 `http://127.0.0.1:8901`,部署时用 `CLOUD_API_URL` 指到内部地址。
   *
   * **不要改成跨域直连** —— 那需要 CORS + `SameSite=None`,而云端会话 cookie 只有在同源时
   * 才是第一方的;同源也让 Cloud 的 Origin 校验只需要认识官网这一个地址。
   * 生产上若 Caddy 已经把这个前缀直接转给了 Cloud,这条 rewrite 不会被用到,留着不影响。
   */
  async rewrites() {
    const cloud = (process.env.CLOUD_API_URL || "http://127.0.0.1:8901").replace(/\/+$/, "");
    return [
      { source: "/api/cloud/v1/:path*", destination: `${cloud}/api/cloud/v1/:path*` },
    ];
  },
};

export default nextConfig;
