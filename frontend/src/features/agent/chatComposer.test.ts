import type { JSONContent } from "@tiptap/react";
import { describe, expect, it, vi } from "vitest";

import { collectReferences, documentText, sendsOnEnter } from "./ChatComposer";
import { REFERENCE_NODE } from "./ReferenceChip";

/**
 * **正文写 `@名字`,id 走结构化字段。**
 *
 * 名字会重、会改、会带空格 —— 拿它当标识迟早出事;而把 32 位十六进制塞进句子会把真正的
 * 那句话挤没。所以这两件事由同一份文档派生出两样东西:给模型读的句子,和给它动手用的清单。
 */
const ref = (kind: string, id: string, name: string): JSONContent => ({
  type: REFERENCE_NODE,
  attrs: { kind, refId: id, name },
});
const text = (value: string): JSONContent => ({ type: "text", text: value });
const doc = (...content: JSONContent[]): JSONContent => ({
  type: "doc",
  content: [{ type: "paragraph", content }],
});

describe("聊天草稿", () => {
  it("引用在句子里就是 @名字", () => {
    const document = doc(text("把 "), ref("asset", "a1", "运镜练习"), text(" 的第三个镜头改长一点"));
    expect(documentText(document)).toBe("把 @运镜练习 的第三个镜头改长一点");
    // 句子里不该出现 id —— 它是给工具用的,不是给人读的。
    expect(documentText(document)).not.toContain("a1");
  });

  it("id 从同一份文档里另收,按出现顺序去重", () => {
    const document = doc(
      ref("note", "n1", "mosael"),
      text(" 和 "),
      ref("asset", "a1", "运镜练习"),
      text(" 还有 "),
      ref("note", "n1", "mosael"),
    );
    expect(collectReferences(document)).toEqual([
      { kind: "note", id: "n1", name: "mosael" },
      { kind: "asset", id: "a1", name: "运镜练习" },
    ]);
  });

  it("段落之间是换行 —— 用户敲的空行是他排的版", () => {
    const document: JSONContent = {
      type: "doc",
      content: [
        { type: "paragraph", content: [text("第一段")] },
        { type: "paragraph", content: [text("第二段")] },
      ],
    };
    expect(documentText(document)).toBe("第一段\n第二段");
  });

  it("空文档发不出任何东西", () => {
    expect(documentText({ type: "doc", content: [{ type: "paragraph" }] })).toBe("");
    expect(collectReferences(undefined)).toEqual([]);
  });

  it("没有 id 的引用不进清单 —— 列出来只会让模型拿空串去调工具", () => {
    expect(collectReferences(doc(ref("asset", "", "无名")))).toEqual([]);
  });
});

/**
 * **`@` 菜单开着时,回车归菜单。**
 *
 * ProseMirror 解 handleKeyDown 时先问视图自己的 props、再问插件 —— 编辑器上挂的那个函数
 * 排在 suggestion 插件**前面**。不显式让路的话,菜单里按回车永远是"把消息发出去"而不是
 * "选中高亮那一条":菜单看着能用、上下键也走得动,就是选不中。这条盯的就是那个让路。
 */
describe("回车归谁", () => {
  const enter = (extra: Partial<KeyboardEvent> = {}) =>
    ({ key: "Enter", shiftKey: false, isComposing: false, ...extra }) as KeyboardEvent;

  it("菜单开着 → 归菜单,不发送", () => {
    expect(sendsOnEnter(enter(), true)).toBe(false);
  });

  it("菜单没开 → 发送", () => {
    expect(sendsOnEnter(enter(), false)).toBe(true);
  });

  it("Shift+回车是换行", () => {
    expect(sendsOnEnter(enter({ shiftKey: true }), false)).toBe(false);
  });

  it("输入法组字中的回车是选词,不是发送", () => {
    // 中文选词时按回车 —— 把它当成发送的话,候选词上不了屏,消息还先飞出去了。
    expect(sendsOnEnter(enter({ isComposing: true }), false)).toBe(false);
  });

  it("别的键一律不管", () => {
    expect(sendsOnEnter(enter({ key: "a" }), false)).toBe(false);
  });
});

describe("候选清单的配额", () => {
  /**
   * 空查询时素材把另外三类挤没过一次:候选按"上限的四倍"去取(每类配额 12),菜单再截到 12 条,
   * 而素材通常就有 12 条以上 —— 它一家占满,笔记/画板/工作流一条都露不出来。
   *
   * 两个数各自看都合理,凑一起才出事。**所以这条不测"函数在某个参数下对不对"** —— 那样测
   * 恰好会漏掉真正出错的地方(调用点),我第一版就是这么写的,把调用点改回四倍它照样绿。
   * 现在配额和截断共用 REFERENCE_MENU_LIMIT,这条钉的是"素材再多,四类也都在结果里"。
   */
  it("素材再多也留得下另外三类的位置", async () => {
    const many = (n: number, prefix: string) =>
      Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i}`, name: `${prefix}-${i}` }));
    vi.resetModules();
    vi.doMock("@/api/client", () => ({
      listAssets: async () => many(50, "a"),
      listBoards: async () => many(50, "b"),
      listWorkflows: async () => many(50, "w"),
      assetThumbnailUrl: (id: string) => `/t/${id}`,
    }));
    //: 笔记走的是另一个模块(api/domains/notes),漏 mock 它的话这条会"少一类"地假绿。
    vi.doMock("@/api/domains/notes", () => ({
      listNotes: async () => many(50, "n").map((x) => ({ id: x.id, title: x.name })),
    }));
    const { searchReferences, REFERENCE_MENU_LIMIT } = await import("./references");

    const out = await searchReferences("ws", "");
    expect([...new Set(out.map((one) => one.kind))].sort()).toEqual(["asset", "board", "note", "workflow"]);
    expect(out.length).toBeLessThanOrEqual(REFERENCE_MENU_LIMIT);
  });
});
