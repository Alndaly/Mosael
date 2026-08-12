/**
 * 界面里不用原生 `<select>`。
 *
 * 原生下拉的弹层由**系统**绘制:配色、圆角、字号、滚动条都不受应用样式约束,深色模式下尤其突兀,
 * 而它旁边就是应用自己的 Combobox —— 同一个表单里两种长相。应用已经有 Combobox / Select 组件,
 * 没有理由再混一个。
 *
 * 这条拦的是「顺手写一个 `<select>`」:它在 diff 里只有一行,和周围的 JSX 混在一起,靠人眼复查
 * 很难注意到,而一旦混进去,后面每个人都会照着抄。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") ? [full] : [];
  });
}

/** 去掉注释,免得「注释里提到 <select>」被当成用了它。 */
const stripComments = (code: string): string =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("原生控件", () => {
  it("没有任何地方直接用 <select>(用 Combobox / Select 组件)", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      /<select[\s>]/.test(stripComments(readFileSync(file, "utf8"))),
    );
    expect(offenders.map((f) => f.slice(SRC.length + 1))).toEqual([]);
  });
});
