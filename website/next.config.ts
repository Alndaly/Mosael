import type { NextConfig } from "next";

import { DEFAULT_LOCALE } from "./src/i18n/config";

const nextConfig: NextConfig = {
  // TypeScript 7 不再暴露 Next 默认走的那套编译器 API,构建会直接失败并让你退回 TS 6。
  // 这个开关让 Next 改用 `tsc` CLI 去做类型检查 —— 保住"依赖取最新版"的前提,而不是为了
  // 迁就构建流程把语言版本降回去。
  experimental: { useTypeScriptCli: true },
  // 仓库根也有 pnpm-workspace.yaml(Electron 应用那套),Turbopack 会误判根目录。
  // 显式指到这里,免得它去别处找依赖。
  turbopack: { root: import.meta.dirname },

  /**
   * 全站路由都在 `[locale]` 段下(见 src/app/[locale]/layout.tsx 的说明),`/` 本身没有页面。
   *
   * 这里不做基于 Accept-Language 的协商:那需要 middleware,而 middleware 会让每个请求都
   * 过一次边缘函数,还会让站点没法纯静态导出。中文是默认语言,英文用户在站头一键就能切,
   * 且切换会记在 URL 里 —— 分享出去的链接自带语言,比嗅探来得可预期。
   */
  async redirects() {
    return [{ source: "/", destination: `/${DEFAULT_LOCALE}`, permanent: false }];
  },
};

export default nextConfig;
