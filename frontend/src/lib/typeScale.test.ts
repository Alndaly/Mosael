/**
 * 界面字号走 token,不写死像素。
 *
 * 写死的 `text-[11px]` 有两个毛病:**不跟屏幕走**(13" 上勉强够看,27" 上成一片蚂蚁),
 * 以及**各写各的** —— 全应用曾有 8 种相近尺寸(10/10.5/11/11.5/12/12.5/13/13.5)混着用,
 * 同一层级的东西在不同页面不一样大,而那半个像素的差别不是设计决定,是 673 处各自写出来的。
 *
 * 现在四档 `text-ui-*` 用 clamp() 跟视口联动(1280 宽处等于原来的像素值,层级关系不变)。
 * 这条棘轮拦的是「下一处又写死一个 px」。
 *
 * 少数确实是特例的尺寸(徽标 9px、大标题 22px…)不在这四档里,列在 ALLOWED 里放行 ——
 * **要放行就写进来**,这样"例外"是一份看得见的清单,而不是散在各文件里的既成事实。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
/** 四档之外的特例:徽标/角标(9–9.5px)、区块大标题(15–22px)。 */
const ALLOWED = new Set(["9px", "9.5px", "15px", "17px", "21px", "22px"]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith("typeScale.test.ts") ? [full] : [];
  });
}

describe("界面字号", () => {
  it("四档 token 覆盖的尺寸不许再写死像素", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      for (const match of readFileSync(file, "utf8").matchAll(/text-\[([0-9.]+px)\]/g)) {
        if (!ALLOWED.has(match[1])) offenders.push(`${file.slice(SRC.length + 1)} → ${match[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
