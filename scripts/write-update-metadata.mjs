#!/usr/bin/env node
/**
 * 给 electron-updater 写 GitHub Release 元数据。
 *
 * DMG 只负责首次安装;Squirrel 更新用带签名的 ZIP。这个脚本从已经验证过的安装包生成
 * latest-mac.yml / latest.yml,因此元数据的 sha512 和真正上传的二进制必然来自同一份文件。
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { argv, exit } from "node:process";

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

function yamlFor(version, file, platform) {
  const name = basename(file);
  // GitHub 会把 Windows 安装包名里的空格规范化成点;元数据必须指向规范化后的下载地址。
  const url = platform === "windows" ? name.replace(/\s+/g, ".") : name;
  const bytes = readFileSync(file);
  const sha512 = createHash("sha512").update(bytes).digest("base64");
  const size = statSync(file).size;
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
  writeFileSync(resolve(outDir, filename), yamlFor(options.version, file, platform));
  console.log(`wrote ${filename} for ${platform}: ${basename(file)}`);
  written += 1;
}
if (written === 0) {
  console.error("no updater metadata written; pass --mac and/or --windows");
  exit(2);
}
