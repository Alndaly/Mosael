import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 画布上的浮层不许整块吞掉滚轮。
 *
 * 触控板上「拖动画布」就是两指滚动(`panOnScroll`),而 React Flow 认 `nowheel`:带这个类的
 * 元素上的滚轮归它自己,不再平移画布。于是一块 560×200 的合成器就是画布上一片滚不动的死区 ——
 * 平移横穿过去时会**当场停住**,而用户完全看不出为什么。
 *
 * 规则是「谁真的会滚,谁才挂 nowheel」:
 *   · 有 max-height + overflow 的滚动区 → 挂(评论卡的正文、设置弹层)
 *   · 固定行数的 textarea → 挂(内容多了真的会滚)
 *   · 只有 min-height、内容多了自己长高的编辑器 → **不挂**(它根本没有可滚的东西)
 *   · 面板外框、内边距、工具行、按钮 → **不挂**
 *
 * 评论输入框那条更早的用例(BoardCommentComposer.dom.test.tsx「触控板滚动经过评论编辑器时
 * 继续交给画布平移」)先定下了这个规矩,这条把它扩到画布上其余的浮层。
 */
const read = (name: string) => readFileSync(join(import.meta.dirname, name), "utf8");

/** 组件根节点那一行的类名(cn(CANVAS_WINDOW_SURFACE_CLASS, "…") 里的字面量部分)。 */
function surfaceClasses(source: string): string[] {
  return [...source.matchAll(/CANVAS_WINDOW_SURFACE_CLASS,\s*"([^"]*)"/g)].map((one) => one[1]);
}

describe("画布浮层与滚轮", () => {
  const panels = [
    "NodeComposer.tsx",
    "NoteComposer.tsx",
    "AudioComposer.tsx",
    "TrimComposer.tsx",
    "CommentCard.tsx",
    "BoardCommentComposer.tsx",
  ];

  for (const name of panels) {
    it(`${name} 的外框不吞滚轮`, () => {
      const found = surfaceClasses(read(name));
      expect(found.length, `${name} 里没找到浮层外框`).toBeGreaterThan(0);
      for (const classes of found) {
        // nodrag / nopan 要留着:那管的是"在这上面按下不该拖走画布",和滚轮是两回事。
        expect(classes, `${name} 的外框整块吞掉了滚轮`).not.toContain("nowheel");
        expect(classes).toContain("nopan");
      }
    });
  }

  it("提示词编辑器不挂 nowheel —— 它只有 min-height,没有东西可滚", () => {
    expect(read("PromptEditor.tsx")).not.toMatch(/nodrag nowheel/);
  });

  it("真的会滚的那两处仍然挂着", () => {
    // 少了这两处,用户在评论正文里滚动会把整张画布拖走 —— 反向的同一个毛病。
    expect(read("CommentCard.tsx")).toMatch(/nowheel max-h-64 overflow-y-auto/);
    expect(read("AudioComposer.tsx")).toMatch(/className="nowheel w-full resize-none/);
  });
});
