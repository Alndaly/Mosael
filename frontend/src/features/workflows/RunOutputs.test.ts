/**
 * 「这一步给了什么」要看得见。
 *
 * 这份数据一直都在(node.finished 事件带着完整 outputs),但画布只从里面挖素材 id,别的一概
 * 丢掉。于是模型回的那段话、抽出来的那个值,跑完了也看不见 —— 想知道只能再接一个"通知"节点
 * 把它打出来。
 */
import { describe, expect, it } from "vitest";

import { outputSummary, outputText } from "@/features/workflows/RunOutputs";
import { assetOutputs, outputRows } from "@/features/workflows/runSteps";
import type { RegistryLike } from "@/features/workflows/analyze";

const registry: RegistryLike = {
  get(nodeType) {
    const table: Record<string, { output_types: Record<string, string>; output_labels?: Record<string, string> }> = {
      ai_generate: { output_types: { asset_id: "asset", generation_id: "text" } },
      llm: { output_types: { text: "text" } },
      //: 分离节点:两份素材 + 一个标量,三个输出都由后端声明了名字。
      separate_audio: {
        output_types: { vocals_asset_id: "asset", background_asset_id: "asset", engine: "text" },
        output_labels: { vocals_asset_id: "人声", background_asset_id: "背景音", engine: "引擎" },
      },
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
    expect(summary?.text).not.toContain("abc123");
  });

  it("取第一个非素材的产出", () => {
    expect(outputSummary(registry, "llm", { text: "模型回的话" })).toEqual({ label: "text", text: "模型回的话" });
  });

  it("**名字跟着值一起给** —— 只有值的话,卡片上就是一个孤零零的 demucs", () => {
    // 分离节点跑完,产出里唯一的标量是引擎名。没有名字时那个词无从判断:是引擎、
    // 是文件名、还是模型?名字由节点自己声明,右边接点上写的也是它。
    expect(outputSummary(registry, "separate_audio", {
      vocals_asset_id: "a1", background_asset_id: "a2", engine: "demucs",
    })).toEqual({ label: "引擎", text: "demucs" });
  });

  it("折行压成一行 —— 卡片上不该出现半截换行", () => {
    expect(outputSummary(registry, "llm", { text: "第一行\n\n  第二行" })?.text).toBe("第一行 第二行");
  });

  it("没跑过就没有这一行", () => {
    expect(outputSummary(registry, "llm", undefined)).toBeNull();
  });

  it("产出全是空值时不给一行空白", () => {
    // 给了空串的话,卡片上会多出一条什么都没有的灰条。
    expect(outputSummary(registry, "llm", { text: "", other: null })).toBeNull();
  });
});

describe("产出摊开成行", () => {
  it("每一行都带着节点声明的名字和类型", () => {
    const rows = outputRows(registry, "separate_audio", { vocals_asset_id: "a1", engine: "demucs" });
    expect(rows).toEqual([
      { key: "vocals_asset_id", label: "人声", type: "asset", value: "a1" },
      { key: "engine", label: "引擎", type: "text", value: "demucs" },
    ]);
  });

  it("没声明名字就退回稳定 key —— 不在前端另编一套", () => {
    expect(outputRows(registry, "llm", { text: "x" })[0].label).toBe("text");
  });

  it("素材那些带着名字一起出来 —— 两份摆在一起时,分不清哪个是哪个正是此前的毛病", () => {
    const rows = outputRows(registry, "separate_audio", {
      vocals_asset_id: "a1", background_asset_id: "a2", engine: "demucs",
    });
    expect(assetOutputs(rows)).toEqual([
      { key: "vocals_asset_id", label: "人声", assetId: "a1" },
      { key: "background_asset_id", label: "背景音", assetId: "a2" },
    ]);
  });

  it("空的素材输出不占位置", () => {
    // 没产出的输出摆上去就是一个永远转圈的取素材请求。
    expect(assetOutputs(outputRows(registry, "separate_audio", { vocals_asset_id: "  " }))).toEqual([]);
  });
});
