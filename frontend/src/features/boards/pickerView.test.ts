/**
 * `@` 菜单里那份**看得见的列表**是怎么来的。
 *
 * 筛选发生在渲染层而不是 `candidates()` 里:@tiptap/suggestion 只在 query / 光标位置变了才
 * 重新取候选,而按一下筛选钮这两样都没变 —— 放进 items() 的筛选按下去纹丝不动,还不报错。
 */
import { describe, expect, it } from "vitest";

import { groupHeadAt } from "./PromptEditor";

const row = (id: string) => ({ id });

describe("分组标题画在哪一行", () => {
  const linked = new Set(["a", "b"]);

  it("第一行总要画 —— 否则第一组没有名字", () => {
    expect(groupHeadAt([row("a"), row("c")], 0, linked)).toBe(true);
  });

  it("同一组里不重复画", () => {
    expect(groupHeadAt([row("a"), row("b")], 1, linked)).toBe(false);
  });

  it("跨到另一组时画 —— 已连接的排完,底下才是素材库", () => {
    expect(groupHeadAt([row("a"), row("c")], 1, linked)).toBe(true);
  });

  it("一条都没连时不会凭空多出一组:整份都是素材库,只在第一行画一次", () => {
    const none = new Set<string>();
    expect(groupHeadAt([row("a"), row("b")], 0, none)).toBe(true);
    expect(groupHeadAt([row("a"), row("b")], 1, none)).toBe(false);
  });
});
