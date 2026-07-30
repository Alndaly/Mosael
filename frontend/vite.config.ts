import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { readFileSync } from "node:fs";

// 版本号只有一个来源:**仓库根** package.json。它是 electron-builder 打包用的版本,也是
// app.getVersion() 的返回值,发版 CI(release.yml 的 Sync app version from tag)也只 bump 它。
// 之前这里读的是 frontend/package.json —— 那个没人 bump,于是 v0.3.0 的包在设置页显示
// "v0.1.0",而同一页的「检查更新」(走 app.getVersion())却正确地说"已是最新版本"。
const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "..", "package.json"), "utf-8")) as { version: string };

export default defineConfig({
  // Relative asset paths so the packaged Electron shell can loadFile() dist.
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  test: {
    // 默认留在 node(纯逻辑测试快得多)。要 DOM 的文件在**文件头**写
    //     /** @vitest-environment jsdom */
    // 逐个声明 —— vitest 4 已移除 environmentMatchGlobs,而按文件声明本来也更明确:
    // 打开一个测试文件就知道它跑在什么环境里,不用回头翻配置。
    //
    // 在此之前没有任何 DOM 环境,于是**任何碰组件的东西都测不了**:24 个测试文件全是纯函数,
    // 所有 UI 回归(下拉滚不动、弹窗关闭时内容先清空、面板贴位)只能靠人手在浏览器里看。
    environment: "node",
    setupFiles: ["./src/test/setup.ts"],
  },
});
