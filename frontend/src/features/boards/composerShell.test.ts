/**
 * 画板上每一块格子面板都套同一个壳(BoardComposerShell),不再各写各的外框。
 *
 * 此前五块面板各有一套:宽 400 / 420 / 560、内边距 p-2 / p-3、发送键有圆的也有带字的胶囊,工具格那块
 * 还是一列带大标签的表单 —— 同一张画布上并排着两种视觉语言,用户一眼就说「节点弹窗和工作流完全不一致」。
 * 壳管外框、宽度档、正文滚底栏钉、「参数」弹层和那枚圆形发送键;面板只交自己的正文和设置。
 *
 * 判据看源码:`features/boards` 里名字带 Composer 的面板文件都渲染 `<BoardComposerShell`,而且不再自己
 * 摆画布浮窗的外框(`NodeToolbar` / `CANVAS_WINDOW_SURFACE_CLASS`)—— 自己摆一个,就又长出一种样子。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const HERE = import.meta.dirname;

/** 不是面板的那两个:壳本身,和按产出者挑面板的那张表(它不画东西,只把格子交给某一块面板)。 */
const NOT_PANELS = new Set(["BoardComposerShell.tsx", "boardComposers.tsx"]);

const panels = readdirSync(HERE).filter(
  (name) => /Composer.*\.tsx$/.test(name) && !name.includes(".test.") && !NOT_PANELS.has(name),
);

describe("画板面板的壳", () => {
  it("扫描面站得住 —— 五块面板都在(生成、写、念、截、工具)", () => {
    expect(panels.sort()).toEqual([
      "ActionComposer.tsx",
      "AudioComposer.tsx",
      "NodeComposer.tsx",
      "NoteComposer.tsx",
      "TrimComposer.tsx",
    ]);
  });

  it.each(panels)("%s 渲染 BoardComposerShell,不自己摆浮窗外框", (name) => {
    const source = readFileSync(join(HERE, name), "utf8");
    expect(source, `${name} 没有套 BoardComposerShell`).toContain("<BoardComposerShell");
    expect(source, `${name} 自己又摆了一个 NodeToolbar`).not.toMatch(/<NodeToolbar\b/);
    expect(source, `${name} 自己又画了一层浮窗外框`).not.toContain("CANVAS_WINDOW_SURFACE_CLASS");
  });
});
