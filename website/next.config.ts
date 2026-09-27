import type { NextConfig } from "next";

import { DEFAULT_LOCALE, LOCALES } from "./src/i18n/config";

const nextConfig: NextConfig = {
  // 自托管部署(deploy/community/docker-compose.yml)跑的是 standalone 产物:`node server.js`,
  // 不需要在镜像里装全量 node_modules。见 website/Dockerfile。
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
  /**
   * 浏览器里的社区请求一律同源发到 `/api/community/*`(刷新令牌的 cookie 因此是第一方的,ADR 0026 §1)。
   *
   * 线上由反代(Caddy)把这一段直接转给社区服务,请求到不了 Next;本地开发没有反代,由这条 rewrite
   * 转到 `COMMUNITY_API_URL`。没配这个变量就不加 —— 社区页此时显示「社区未开放」,也没有东西可转。
   * 转发时路径原样保留:社区服务自己就挂在 `/api/community/v1` 下。
   */
  async rewrites() {
    const target = process.env.COMMUNITY_API_URL?.trim().replace(/\/+$/, "");
    return target ? [{ source: "/api/community/:path*", destination: `${target}/api/community/:path*` }] : [];
  },

  async redirects() {
    return [
      { source: "/", destination: `/${DEFAULT_LOCALE}`, permanent: false },
      // 桌面应用和社区服务给出的链接不带语言段:发布后的条目页、设置里的「我的提交 / 我的分享」、
      // 设备授权的 verification_uri_complete(`/device?code=…`,查询串跟着跳转带过去)。和 `/` 一样
      // 送到默认语言,访客在站头切语言即可。不做 Accept-Language 协商,理由同上。
      ...["workflows", "plugins"].flatMap((section) => [
        { source: `/${section}`, destination: `/${DEFAULT_LOCALE}/${section}`, permanent: false },
        { source: `/${section}/:slug`, destination: `/${DEFAULT_LOCALE}/${section}/:slug`, permanent: false },
      ]),
      { source: "/device", destination: `/${DEFAULT_LOCALE}/device`, permanent: false },
      { source: "/boards", destination: `/${DEFAULT_LOCALE}/boards`, permanent: false },
      { source: "/b/:slug", destination: `/${DEFAULT_LOCALE}/b/:slug`, permanent: false },
      { source: "/u/:handle", destination: `/${DEFAULT_LOCALE}/u/:handle`, permanent: false },
      // 「我的提交 / 我的分享」在账号页上是两个锚点;带不带语言段都认。
      ...["submissions", "shares", "sessions"].flatMap((anchor) => [
        { source: `/me/${anchor}`, destination: `/${DEFAULT_LOCALE}/account#${anchor}`, permanent: false },
        { source: `/:locale(${LOCALES.join("|")})/me/${anchor}`, destination: `/:locale/account#${anchor}`, permanent: false },
      ]),
      // 四个对象存储插件合成了一个随应用内置的「对象存储」。老版本插件清单里的文档链接、外面贴过的地址
      // 还指着各自的页面 —— 转到合并后的那一页,而不是 404。
      ...["aliyun-oss", "aws-s3", "tencent-cos", "volcengine-tos"].map((slug) => ({
        source: `/:locale/plugins/${slug}`,
        destination: "/:locale/plugins/object-storage",
        permanent: true,
      })),
    ];
  },
};

export default nextConfig;
