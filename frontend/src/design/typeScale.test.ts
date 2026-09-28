/**
 * 界面字号走 token,不写死像素。
 *
 * 写死的 `text-[11px]` 有两个毛病:**不跟屏幕走**(13" 上勉强够看,27" 上成一片蚂蚁),
 * 以及**各写各的** —— 全应用曾有 8 种相近尺寸(10/10.5/11/11.5/12/12.5/13/13.5)混着用,
 * 同一层级的东西在不同页面不一样大,而那半个像素的差别不是设计决定,是 673 处各自写出来的。
 *
 * 现在字号走 `--text-ui-*` 这一组 token(定义在 `design/tokens.css`),用哪几档由那份文件说了算。
 * 这条棘轮拦的是「下一处又写死一个 px」。
 *
 * **这段说明本身曾经在说谎**:它写着"四档"且"用 clamp() 跟视口联动",而 token 表里是六个、
 * 而且是固定像素 —— 棘轮的 docstring 是这套体系里信息密度最高的一批文字,却没有任何东西
 * 在守它。所以现在这里不写档数:档位从 `tokens.css` 读(见 `tiers()`),一个数写在散文里,
 * 唯一的作用是在下一次加档时骗人。
 *
 * 少数确实是特例的尺寸(徽标 9px、大标题 22px…)不在这组 token 里,列在 ALLOWED 里放行 ——
 * **要放行就写进来**,这样"例外"是一份看得见的清单,而不是散在各文件里的既成事实。
 *
 * **扫描面包括 `.css`。** 第一版只扫 `.ts/.tsx`,理由大概是"写死像素是 Tailwind 的
 * `text-[11px]` 那种写法" —— 而同一件事在样式表里写成 `font-size: 11px`,它一个都看不见。
 * 实测那时功能页的样式表里有十一处未走 token 的字号,这条棘轮全程是绿的。
 * 判据没变,变的是它往哪儿看。
 *
 * `design/tokens.css` 不在扫描面内:那是**定义**这几档的地方,扫它等于让定义违反自己。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/** `design/tokens.css` 里现有的那几档 —— **档位由那份文件说了算**,这里不复述一个数。 */
function tiers(): string[] {
  const css = readFileSync(join(SRC, "design", "tokens.css"), "utf8");
  return [...css.matchAll(/--text-ui-([\w-]+):\s*([\d.]+px)/g)].map((one) => `${one[1]}=${one[2]}`);
}
/**
 * token 之外的特例:徽标/角标(9–10px)、正文与区块标题(13–26px)。
 *
 * 13px 和 10px 是从样式表那一侧扫出来的:token 表里没有对应档(11/12/14/16/18/32),
 * 而把它们就近归一会改变现有的视觉层级 —— 那是一次设计决定,不该顺手夹在一条棘轮的改动里。
 * 26px 是笔记正文的 h1,它跟的是文章排版而不是界面控件那一套。
 */
const ALLOWED = new Set([
  "9px", "9.5px", "10px", "13px", "15px", "17px", "18px", "21px", "22px", "26px",
]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    if (entry.name.endsWith("typeScale.test.ts")) return [];
    // tokens.css 是**定义**这几档的地方 —— 扫它等于让定义违反自己。
    if (full.endsWith(join("design", "tokens.css"))) return [];
    return /\.(ts|tsx|css)$/.test(entry.name) ? [full] : [];
  });
}

/** 两种写法,同一件事:Tailwind 的 `text-[11px]`,和样式表里的 `font-size: 11px`。 */
const HARDCODED = /text-\[([0-9.]+px)\]|font-size:\s*([0-9.]+px)/g;

describe("界面字号", () => {
  it("token 覆盖的尺寸不许再写死像素", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      for (const match of readFileSync(file, "utf8").matchAll(HARDCODED)) {
        const size = match[1] ?? match[2];
        if (!ALLOWED.has(size)) offenders.push(`${file.slice(SRC.length + 1)} → ${size}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("档位从 tokens.css 读,不在说明里复述一个数", () => {
    // 这段说明曾经写着"四档",而表里是六个 —— 一个写在散文里的数,唯一的作用是下次加档时骗人。
    const found = tiers();
    expect(found.length).toBeGreaterThanOrEqual(5);
    expect(found.join(" ")).toContain("2xs=");
  });

  it("扫描面里确实有样式表 —— 别再变成只扫 .ts", () => {
    const files = sourceFiles(SRC);
    expect(files.some((one) => one.endsWith(".css")), "一份 .css 都没扫到").toBe(true);
    expect(files.some((one) => one.endsWith(".tsx"))).toBe(true);
  });
});
