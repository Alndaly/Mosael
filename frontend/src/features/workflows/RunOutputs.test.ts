/**
 * 「这一步给了什么」要看得见。
 *
 * 这份数据一直都在(node.finished 事件带着完整 outputs),但画布只从里面挖素材 id,别的一概
 * 丢掉。于是模型回的那段话、抽出来的那个值,跑完了也看不见 —— 想知道只能再接一个"通知"节点
 * 把它打出来。
 */
import { describe, expect, it } from "vitest";

import { outputSummary, outputText } from "@/features/workflows/RunOutputs";
import type { RegistryLike } from "@/features/workflows/analyze";

const registry: RegistryLike = {
  get(nodeType) {
    const table: Record<string, { output_types: Record<string, string> }> = {
      ai_generate: { output_types: { asset_id: "asset", generation_id: "text" } },
      llm: { output_types: { text: "text" } },
    };
    return table[nodeType];
  },
};

describe("把任意产出变成可读文本", () => {
  it("对象和数组给缩进过的 JSON", () => {
    expect(outputText({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(outputText([1, 2])).toBe("[\n  1,\n  2\n]");
  });

  it("标量原样", () => {
    expect(outputText("hi")).toBe("hi");
    expect(outputText(0)).toBe("0");
    expect(outputText(false)).toBe("false");
  });

  it("空值给空串,不要打出 null 这个词", () => {
    // 界面上一个大写的 "null" 比什么都不显示更让人以为哪里坏了。
    expect(outputText(null)).toBe("");
    expect(outputText(undefined)).toBe("");
  });

  it("带环的对象不炸,退回 String()", () => {
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    expect(() => outputText(loop)).not.toThrow();
  });
});

describe("节点卡片上那一行摘要", () => {
  it("跳过素材 —— 它另有缩略图,裸 id 也不是给人看的", () => {
    const summary = outputSummary(registry, "ai_generate", { asset_id: "abc123", generation_id: "g1" });
    expect(summary).not.toContain("abc123");
  });

  it("取第一个非素材的产出", () => {
    expect(outputSummary(registry, "llm", { text: "模型回的话" })).toBe("模型回的话");
  });

  it("折行压成一行 —— 卡片上不该出现半截换行", () => {
    expect(outputSummary(registry, "llm", { text: "第一行\n\n  第二行" })).toBe("第一行 第二行");
  });

  it("没跑过就是空的", () => {
    expect(outputSummary(registry, "llm", undefined)).toBe("");
  });

  it("产出全是空值时不给一行空白", () => {
    // 给了空串的话,卡片上会多出一条什么都没有的灰条。
    expect(outputSummary(registry, "llm", { text: "", other: null })).toBe("");
  });
});
