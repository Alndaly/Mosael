/**
 * **会裁切的盒子不能用 `leading-none`。**
 *
 * `leading-none` 是 `line-height: 1` —— 行盒正好等于字号高。而字形要的比字号高:拉丁字母的
 * `g`/`p`/`y` 往下伸,中文是满字身。多出来的部分平时只是溢出行盒,照样画得出来,看不出问题;
 * 一旦这个盒子(或它裹着的文本)带了 `overflow: hidden` —— `truncate`、`line-clamp-*` 都带 ——
 * 溢出的那一截就被切掉了。
 *
 * 生成页右栏的模型下拉撞过这一下:14px 的字,可见高 14px、内容要 16px,**上下各切掉 1px**。
 * 截图上看是"字被削了一层",而 className 里只写着 `leading-none` 和 `truncate` 两个看起来
 * 毫不相干的类。
 *
 * 所以这道棘轮盯的是**这两个类的共现**,而不是某一个页面:同一个元素上写了,或者一个
 * `leading-none` 的元素里裹着 `truncate` 的子元素,都算。
 *
 * 图标、角标、单字标签那些不裁切的地方,`leading-none` 仍然是对的 —— 它们不在这条规则里,
 * 因为它们没有 overflow hidden。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const CLIPPING = /\b(?:truncate|line-clamp-\d+|overflow-hidden)\b/;

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === "node_modules" ? [] : tsxFiles(path);
    return path.endsWith(".tsx") && !path.includes(".test.") ? [path] : [];
  });
}

/** 去掉注释 —— 免得棘轮被"注释里提到 leading-none"喂饱(这个仓库出过空棘轮)。 */
function strip(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

interface Hit {
  file: string;
  line: number;
  snippet: string;
}

function findHits(): Hit[] {
  const hits: Hit[] = [];
  for (const path of tsxFiles(SRC)) {
    const code = strip(readFileSync(path, "utf8"));
    const lines = code.split("\n");
    lines.forEach((line, index) => {
      if (!line.includes("leading-none")) return;
      // 同一个 className 里就撞上了。
      const own = /className=\{?["'`][^"'`]*leading-none[^"'`]*["'`]/.exec(line);
      const sameAttr = own && CLIPPING.test(own[0]);
      // 或者:这个元素裹着的下面几行里有裁切的子元素(本例的形状)。
      const nested = lines.slice(index + 1, index + 5).some((next) => CLIPPING.test(next));
      if (sameAttr || nested) {
        hits.push({ file: path.slice(SRC.length + 1), line: index + 1, snippet: line.trim().slice(0, 90) });
      }
    });
  }
  return hits;
}

describe("会裁切的盒子不能用 leading-none", () => {
  it("全库没有 leading-none 与 truncate/line-clamp 的共现", () => {
    const hits = findHits();
    expect(hits.map((h) => `${h.file}:${h.line}  ${h.snippet}`)).toEqual([]);
  });

  it("这道棘轮扫得到东西 —— 别变成空转", () => {
    // 假阴性比红更危险:哪天目录结构变了、扫不到任何文件,上面那条会真空通过。
    expect(tsxFiles(SRC).length).toBeGreaterThan(50);
  });
});
