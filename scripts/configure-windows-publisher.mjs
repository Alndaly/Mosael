#!/usr/bin/env node
/**
 * 把 Windows 签名主体写进 `build/app-update.yml`，并拒绝“没有发布者主体”的发版构建。
 *
 * electron-updater 在 `publisherName` 为空时**直接跳过** Authenticode 校验；这个文件会被
 * electron-builder 原样塞进安装包的 Resources，因此它是更新链的信任根，不能缺。
 */
import fs from "node:fs";
import path from "node:path";

const publisher = String(process.env.WIN_PUBLISHER_NAME || "").trim();
if (!publisher) {
  console.error("WIN_PUBLISHER_NAME is required: without it electron-updater skips Windows signature checks.");
  process.exit(1);
}
const file = path.resolve("build/app-update.yml");
const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).filter((line) => !line.startsWith("publisherName:"));
lines.push(`publisherName: ${JSON.stringify(publisher)}`);
fs.writeFileSync(file, `${lines.join("\n").replace(/\n+$/, "")}\n`);
console.log(`Windows publisher: ${publisher}`);
