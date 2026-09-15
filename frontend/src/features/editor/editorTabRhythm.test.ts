/**
 * 剪辑台上的分段 tab 只有一种长相。
 *
 * 左栏(素材 / 逐字稿 / 字幕 / 配音)用的是剪辑台自己那套 `.editor-mode-tab`:32px 的裸标签,
 * 选中态填 `--accent`。右侧检查器的「属性 / 调色」一度用通用的 `SEGMENTED_LIST` —— 它会在
 * 两个标签外面再包一层 40px 的承托底色,于是同一屏上并排出现了两种分段控件,而且那层壳塞进
 * 44px 的面板头里上下只剩 2px(同排的图标按钮才 24px)。
 *
 * 这条值得钉:两种写法**各自都对**,错的是它们同时出现在一块屏幕上 —— 这种错读代码看不出来,
 * 要把两个文件并排看才发现。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const EDITOR = join(import.meta.dirname);

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

describe("剪辑台的分段 tab", () => {
  it("不混用通用 SEGMENTED_LIST —— 剪辑台有自己那一套", () => {
    // 认的是**真的用了它**(从 ui/tabs 里 import 进来),不是提到这个名字 —— 否则解释
    // "为什么不用它" 的那句注释会把自己判成违规,而注释恰恰是最该留下的东西。
    const offenders = sources(EDITOR)
      .filter((file) =>
        /import\s*\{[^}]*\b(?:SEGMENTED_LIST|segmentedTriggerClass)\b[^}]*\}\s*from\s*["'][^"']*ui\/tabs["']/
          .test(readFileSync(file, "utf8")),
      )
      .map((file) => relative(EDITOR, file));
    expect(offenders, [
      "剪辑台的 tab 用 `.editor-mode-tab`(见 editor.css),和左栏那排同一个长相。",
      "通用的 SEGMENTED_LIST 会多包一层承托底色,并排看就是两种控件。",
    ].join("\n")).toEqual([]);
  });

  it("面板头放得下一个 32px 的控件,而且上下留得出空", () => {
    const css = readFileSync(join(EDITOR, "editor.css"), "utf8");
    const header = Number(/\.editor-pane-header\s*\{[^}]*min-height:\s*(\d+)px/.exec(css)?.[1]);
    const control = Number(/--editor-control-height:\s*(\d+)px/.exec(css)?.[1]);
    expect(header).toBeGreaterThan(0);
    expect(control).toBe(32);
    // 上下各 6px。挤到 2px 的那一版正是加了外壳之后的样子。
    expect((header - control) / 2).toBeGreaterThanOrEqual(6);
  });
});
