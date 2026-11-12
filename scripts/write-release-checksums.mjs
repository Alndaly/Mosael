#!/usr/bin/env node
/** 为本次发布目录里的安装包/元数据生成 SHA256SUMS；R2 与 GitHub Release 使用同一份。 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const release = path.resolve(process.argv[process.argv.indexOf("--release") + 1] || "release");
const names = fs.readdirSync(release).filter((name) => {
  if (!fs.statSync(path.join(release, name)).isFile()) return false;
  return name !== "SHA256SUMS" && !name.endsWith(".blockmap") ? /\.(dmg|exe|zip|yml|json)$/i.test(name) : false;
});
const lines = names.sort().map((name) => {
  const digest = createHash("sha256").update(fs.readFileSync(path.join(release, name))).digest("hex");
  return `${digest}  ${name}`;
});
fs.writeFileSync(path.join(release, "SHA256SUMS"), `${lines.join("\n")}\n`);
console.log(`SHA256SUMS: ${names.length} files`);
