#!/usr/bin/env node
/**
 * 为发布目录生成 SHA256SUMS:CI 的 release/、本机交接的 dist/VERSION/ 都用它,R2 与 GitHub Release 同一份。
 *
 * 覆盖的是「会被用户下载」的那一套:安装包、更新 ZIP、差分更新的 .blockmap、更新元数据、插件包与市场索引。
 * .blockmap 必须在内 —— 更新器按它 Range 下载变化块,它被换掉和安装包被换掉一样危险。
 * electron-builder 的调试产物(builder-debug.yml 等)和生成在后面的 index.html 不在其中。
 *
 *   node scripts/write-release-checksums.mjs --release dist/2.6.15
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const PUBLISHED = /\.(dmg|exe|zip|blockmap|yml|json)$/i;
const BUILDER_INTERNALS = /^builder-/;

function isPublishedAsset(name) {
  return PUBLISHED.test(name) && !BUILDER_INTERNALS.test(name);
}

function writeReleaseChecksums(release) {
  const names = fs
    .readdirSync(release, { withFileTypes: true })
    .filter((entry) => entry.isFile() && isPublishedAsset(entry.name))
    .map((entry) => entry.name)
    .sort();
  const lines = names.map((name) => {
    const digest = createHash("sha256").update(fs.readFileSync(path.join(release, name))).digest("hex");
    return `${digest}  ${name}`;
  });
  fs.writeFileSync(path.join(release, "SHA256SUMS"), `${lines.join("\n")}\n`);
  return names;
}

const flag = process.argv.indexOf("--release");
const release = path.resolve(flag === -1 ? "release" : process.argv[flag + 1]);
console.log(`SHA256SUMS: ${writeReleaseChecksums(release).length} files`);
