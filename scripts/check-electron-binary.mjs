#!/usr/bin/env node
/**
 * 开发启动前确认 Electron 二进制真的在。
 *
 * **为什么需要这一步**:`electron:dev` 那一行显式清空了所有代理变量 —— 那是必须的,回环探活
 * 走代理会一直挂着不返回(见 frontend/package.json 里 `//electron:dev` 那条说明)。代价是同
 * 一条命令里的 `electron` 也失去了代理,而它在二进制缺失时会去 GitHub 下载。网络到不了时它
 * **不报错,只是不动**,日志停在 `Downloading Electron binary...`,而现象是「vite 和后端都起来
 * 了、app 就是不出现」——极难往下载上想。
 *
 * 升级 Electron 版本、`rm -rf node_modules`、换一台机器,都会重演。
 *
 * **只诊断,不代下载。** 静默替用户下载正是上面那个卡死的形状:它同样可能挂十分钟,而用户
 * 面对的还是一个不动的终端。说清楚发生了什么、给一条能粘贴的命令,比替他猜网络环境有用。
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const pkg = path.join(root, "node_modules", "electron");

function version() {
  try {
    return JSON.parse(readFileSync(path.join(pkg, "package.json"), "utf8")).version;
  } catch {
    return null;
  }
}

function binary() {
  // `path.txt` 是 electron 的 postinstall 写的:相对 dist/ 的可执行文件路径。
  // 它空着或 dist/ 不在,就说明二进制没落地 —— 只看目录在不在会漏掉「装了一半」。
  try {
    const relative = readFileSync(path.join(pkg, "path.txt"), "utf8").trim();
    if (!relative) return null;
    const file = path.join(pkg, "dist", relative);
    return existsSync(file) ? file : null;
  } catch {
    return null;
  }
}

const installed = version();
if (!installed) {
  console.error("\n找不到 electron 包。先 `pnpm install`。\n");
  process.exit(1);
}

if (!binary()) {
  console.error(
    `\nElectron ${installed} 的二进制还没下载好,现在启动会卡在「Downloading Electron binary...」不动。\n\n` +
      `装它(镜像下载,不依赖代理):\n\n` +
      `  ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ node node_modules/electron/install.js\n\n` +
      `已经能直连 GitHub 的话,去掉前面那个变量也行。装完重新 \`pnpm dev\`。\n`,
  );
  process.exit(1);
}
