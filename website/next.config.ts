import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // TypeScript 7 不再暴露 Next 默认走的那套编译器 API,构建会直接失败并让你退回 TS 6。
  // 这个开关让 Next 改用 `tsc` CLI 去做类型检查 —— 保住"依赖取最新版"的前提,而不是为了
  // 迁就构建流程把语言版本降回去。
  experimental: { useTypeScriptCli: true },
  // 仓库根也有 pnpm-workspace.yaml(Electron 应用那套),Turbopack 会误判根目录。
  // 显式指到这里,免得它去别处找依赖。
  turbopack: { root: import.meta.dirname },
};

export default nextConfig;
