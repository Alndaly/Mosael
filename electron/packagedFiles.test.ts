/**
 * 装进安装包(app.asar)的只有运行时要的东西。
 *
 * `electron/**` 此前把这个目录下的一切都收了进去:`*.test.ts` 和 TypeScript 源码(运行时只用
 * `.cjs` 和打好的 `*.bundle.cjs`),于是 1.5.1 的包里带着测试用的假凭据(`cscKeyPassword: …`、
 * `api_key=sk-example-…`)—— 不是泄露,但每次安全扫描都会被它绊一下。更要紧的是兜底:本机打包时
 * electron-builder 不会自己排除 `.env`、证书、私钥,谁在这个目录里放一份,它就进包了。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const files: string[] = JSON.parse(fs.readFileSync(path.resolve(__dirname, "..", "package.json"), "utf8")).build.files;

describe("安装包收哪些文件", () => {
  it("不收 TypeScript 源码和测试", () => {
    expect(files).toContain("!electron/**/*.ts");
  });

  it("不收 .env、证书、私钥", () => {
    expect(files).toContain("!**/.env*");
    const secrets = files.find((pattern) => pattern.startsWith("!**/*.{"));
    for (const ext of ["p12", "pfx", "key", "pem"]) expect(secrets).toContain(ext);
  });

  it("运行时 require 的都是 .cjs,排除 .ts 不会漏掉要用的东西", () => {
    const main = fs.readFileSync(path.resolve(__dirname, "main.cjs"), "utf8");
    const local = [...main.matchAll(/require\(["'](\.\/[^"']+)["']\)/g)].map((m) => m[1]);
    expect(local.length).toBeGreaterThan(0);
    expect(local.filter((spec) => !spec.endsWith(".cjs"))).toEqual([]);
  });
});
