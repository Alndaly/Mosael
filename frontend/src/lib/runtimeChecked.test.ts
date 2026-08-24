/**
 * 「还没测过」不能显示成「跑不起来」。
 *
 * 后端把这两件事分开给了:`runtime_ready`(跑得起来吗)和 `runtime_checked`(测过了吗)。
 * 探测要起子进程去 import f5-tts / funasr,所以**第一次拿到的一定是「还没测过」**——
 * 此时 runtime_ready 是 false,但它的含义是"未知",不是"不行"。
 *
 * 线上翻车过:配音面板只看了 runtime_ready,于是明明装好的引擎一直写着「未装好」,
 * 而用户进一次设置页(那边会把这份缓存刷掉)就"好了" —— 现象诡异,病根只是少读了一个字段。
 *
 * 这条棘轮拦的就是「下一处只读一半」:凡是读 runtime_ready 的文件,必须也读 runtime_checked。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith("runtimeChecked.test.ts") ? [full] : [];
  });
}

/** 去掉注释再判 —— 否则"注释里提到 runtime_checked"也会被算成读了它,棘轮等于没拦。 */
const stripComments = (code: string): string =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");

describe("运行环境探测的三态", () => {
  it("读 runtime_ready 的地方必须同时读 runtime_checked", () => {
    const offenders = sourceFiles(SRC).filter((file) => {
      // 生成的 API 类型只是字段声明,不是"用法"。
      if (file.includes("/api/generated/")) return false;
      const code = stripComments(readFileSync(file, "utf8"));
      return code.includes("runtime_ready") && !code.includes("runtime_checked");
    });
    expect(offenders.map((f) => f.slice(SRC.length + 1))).toEqual([]);
  });
});
