#!/usr/bin/env node
/**
 * 给 electron-updater 写 GitHub Release 元数据。
 *
 * latest-mac.yml / latest.yml 和对应的 .blockmap,因此元数据的 sha512 和真正上传的二进制
 * 必然来自同一份文件;两个平台的差分下载都读同目录下的 blockmap。
 */
import { existsSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { argv, exit } from "node:process";
import { basename, resolve } from "node:path";

// app-builder-lib 是 electron-builder 的依赖,不在根 package.json 里重复声明一份。
// 从 electron-builder 的真实安装位置解析,pnpm 的隔离依赖布局下也能找到同一个实现。
const require = createRequire(import.meta.url);
const { buildBlockMap } = createRequire(require.resolve("electron-builder/package.json"))(
  "app-builder-lib/out/targets/blockmap/blockmap.js",
);

function args() {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    out[key.slice(2)] = argv[i + 1];
    i += 1;
  }
  return out;
}

async function yamlFor(version, file, platform) {
  const name = basename(file);
  // GitHub 会把 Windows 安装包名里的空格规范化成点;元数据必须指向规范化后的下载地址。
  const url = platform === "windows" ? name.replace(/\s+/g, ".") : name;
  // 输出文件存在时 buildBlockMap 不改原安装包,返回的仍是它的 size / sha512。
  const { size, sha512 } = await buildBlockMap(file, "gzip", `${file}.blockmap`);
  return [
    `version: ${version}`,
    `path: ${url}`,
    `sha512: ${sha512}`,
    "files:",
    `  - url: ${url}`,
    `    sha512: ${sha512}`,
    `    size: ${size}`,
    "",
  ].join("\n");
}

const options = args();
if (!options.version || !options.out) {
  console.error("usage: node scripts/write-update-metadata.mjs --version X.Y.Z --out release [--mac signed.zip] [--windows installer.exe]");
  exit(2);
}
const outDir = resolve(options.out);
const jobs = [
  ["mac", "latest-mac.yml"],
  ["windows", "latest.yml"],
];
let written = 0;
for (const [platform, filename] of jobs) {
  const file = options[platform];
  if (!file) continue;
  if (!existsSync(file)) {
    console.error(`missing ${platform} artifact: ${file}`);
    exit(1);
  }
  writeFileSync(resolve(outDir, filename), await yamlFor(options.version, file, platform));
  console.log(`wrote ${filename} for ${platform}: ${basename(file)} + .blockmap`);
  written += 1;
}
if (written === 0) {
  console.error("no updater metadata written; pass --mac and/or --windows");
  exit(2);
}
