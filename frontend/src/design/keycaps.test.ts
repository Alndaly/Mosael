/**
 * 键帽只有一种长相:`<kbd>` 只在 components/ui/kbd.tsx 里写。
 *
 * 起因是时间线的快捷键表:同一列里 ⌘ ⇧ ← → 比字母大一圈、还往下沉,而顶栏搜索按钮上那颗 ⌘K
 * 好好的。四处各写一份键帽样式 —— 时间线用等宽 + 加厚底边,标记旗用等宽 + 底色,搜索按钮用
 * 正文字体 —— 等宽那几处的符号回落到了 Apple Symbols。改一处好一处,下一处照样歪。
 *
 * 所以认的是**写法**:页面里手写 `<kbd` 或者用 `[&_kbd]` 从外面给键帽上样式,都算自己又画了
 * 一颗键帽。用 `Kbd` / `KbdGroup`。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
const HOME = join("components", "ui", "kbd.tsx");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sources(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

describe("键帽", () => {
  it("只有 components/ui/kbd.tsx 画键帽", () => {
    const offenders = sources(SRC)
      .filter((file) => relative(SRC, file) !== HOME)
      .filter((file) => /<kbd[\s>]|\[&_kbd\]/.test(readFileSync(file, "utf8")))
      .map((file) => relative(SRC, file));
    expect(offenders, "用 @/components/ui/kbd 的 Kbd(单个键)或 KbdGroup(几个键任选其一)。").toEqual([]);
  });

  it("键帽的字体是系统界面字体,不是等宽", () => {
    const kbd = readFileSync(join(SRC, HOME), "utf8");
    expect(kbd).toContain("font-kbd");
    expect(kbd).not.toContain("font-mono");
    const tokens = readFileSync(join(SRC, "design", "tokens.css"), "utf8");
    expect(/--font-kbd:\s*-apple-system/.test(tokens), "--font-kbd 要由系统界面字体打头").toBe(true);
  });
});
