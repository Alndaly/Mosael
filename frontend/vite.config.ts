import { defineConfig, type Plugin } from "vite";
import { createRequire } from "node:module";
import fs from "node:fs";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import pkg from "../package.json" with { type: "json" };
import { DECODER_FILES, DECODER_PREFIX } from "./src/features/scenes/decoderAssets.ts";

// 版本号只有一个来源:**仓库根** package.json。它是 electron-builder 打包用的版本,也是
// app.getVersion() 的返回值,发版 CI(release.yml 的 Sync app version from tag)也只 bump 它。
// 之前这里读的是 frontend/package.json —— 那个没人 bump,于是 v0.3.0 的包在设置页显示
// "v0.1.0",而同一页的「检查更新」(走 app.getVersion())却正确地说"已是最新版本"。
//
// **用 import 而不是 readFileSync**:Vite 会把配置 import 到的文件当作配置依赖并在它变化时重启
// 开发服务器;`readFileSync` 读到的东西它看不见 —— 于是跨过一次版本 bump 的长命开发服务器会把
// 旧版本号一直 define 下去(实际发生过:7 月 30 日起的开发服务器在 8 月 2 日 bump 到 0.8.0 之后
// 仍然满屏显示 v0.7.0,而代码和打出来的包都是对的)。
// 用 import.meta.dirname 而不是 __dirname:Vite 8 的 `configLoader: "native"`(未来版本的默认值)
// 下不提供 CJS 的 __dirname,当前版本只是警告,默认值一换配置就直接加载失败。
const here = import.meta.dirname;

/**
 * 把 three 自带的 KTX2 / Draco 解码器摆到 `/three/` 下。
 *
 * **为什么不能走 `?url` 导入**:`KTX2Loader.setTranscoderPath` / `DRACOLoader.setDecoderPath`
 * 要的是一个**目录**,它们自己去拼 `basis_transcoder.js`、`.wasm` 这些文件名。而 `?url` 会把
 * 文件哈希改名,拼出来的地址就不存在了。
 *
 * **为什么不直接把文件签进 public/**:那样它们会和 node_modules 里的 three 版本脱钩 ——
 * 升级 three 之后解码器还是旧的,而 wasm 和 loader 是配套的,不匹配时的症状是"某些模型解不开",
 * 没有任何地方会报"版本对不上"。这里从**装着的那个 three** 里取,升级就自动跟上。
 *
 * 都是本地文件,不走 CDN:这个应用要能离线跑。
 */
function threeDecoders(): Plugin {
  //: 从 three 自己的 exports 里解一个真实文件再回推目录 —— `three/package.json` 不在
  //: exports 映射里,直接 resolve 它会 ERR_PACKAGE_PATH_NOT_EXPORTED。
  const libs = path.dirname(
    createRequire(import.meta.url).resolve("three/examples/jsm/libs/meshopt_decoder.module.js"),
  );
  const files = DECODER_FILES;
  return {
    name: "mosael:three-decoders",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const name = files.find((file) => req.url?.startsWith(`/${DECODER_PREFIX}/${file}`));
        if (!name) return next();
        res.setHeader("Content-Type", name.endsWith(".wasm") ? "application/wasm" : "text/javascript");
        fs.createReadStream(path.join(libs, name)).pipe(res);
      });
    },
    generateBundle() {
      for (const name of files) {
        // fileName 原样落盘(不哈希)—— 上面说过,loader 拼的是固定文件名。
        this.emitFile({ type: "asset", fileName: `${DECODER_PREFIX}/${name}`, source: fs.readFileSync(path.join(libs, name)) });
      }
    },
  };
}

export default defineConfig({
  // Relative asset paths so the packaged Electron shell can loadFile() dist.
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react(), tailwindcss(), threeDecoders()],
  resolve: {
    alias: {
      "@": path.resolve(here, "src"),
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
    // electron/ 下的主进程代码也归这一套测试跑。它此前没有任何测试 —— 而 esbuild 只打包、
    // 不看类型也不跑用例,于是那半边代码的回归只能等打包后在真机上撞见(登录项那条就是)。
    include: ["src/**/*.{test,spec}.?(c|m)[jt]s?(x)", "../electron/**/*.{test,spec}.?(c|m)[jt]s?(x)"],
  },
});
