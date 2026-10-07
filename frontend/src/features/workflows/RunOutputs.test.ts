/**
 * 「这一步给了什么」要看得见。
 *
 * 这份数据一直都在(node.finished 事件带着完整 outputs),但画布只从里面挖素材 id,别的一概
 * 丢掉。于是模型回的那段话、抽出来的那个值,跑完了也看不见 —— 想知道只能再接一个"通知"节点
 * 把它打出来。
 */
import { describe, expect, it } from "vitest";

import { outputSummary, outputText } from "@/features/workflows/RunOutputs";
import { assetOutputs, outputRows, repeatsOf } from "@/features/workflows/runSteps";
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
      //: 一张 ComfyUI 工作流的工具:那个保存节点的口、第一份产出、全部产出(一串 id,是 JSON)。
      comfy: {
        output_types: { image_9: "asset", asset_id: "asset", asset_ids: "json" },
        output_labels: { image_9: "图 · 预览图像", asset_id: "第一份产出", asset_ids: "全部产出" },
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

  it("一个素材口交了一串(batch 2):每一份各是一项,带着那个口的名字 —— 此前一串的整行丢掉,口上只看得到一张", () => {
    const rows = outputRows(registry, "comfy", { image_9: ["a1", "a2", ""], asset_id: "a1", asset_ids: ["a1", "a2"] });
    expect(assetOutputs(rows)).toEqual([
      { key: "image_9", label: "图 · 预览图像", assetId: "a1" },
      { key: "image_9", label: "图 · 预览图像", assetId: "a2" },
      { key: "asset_id", label: "第一份产出", assetId: "a1" },
    ]);
  });

  it("空的素材输出不占位置", () => {
    // 没产出的输出摆上去就是一个永远转圈的取素材请求。
    expect(assetOutputs(outputRows(registry, "separate_audio", { vocals_asset_id: "  " }))).toEqual([]);
  });
});

describe("交的就是上面那几份的口", () => {
  //: 维护者跑 batch 2 的 krea2 工作流,检查器里第一张图摆了两遍,底下再跟一段两个 id 的 JSON:「这个有啥用」。
  const comfy = { image_9: ["img1", "img2"], asset_id: "img1", asset_ids: ["img1", "img2"], texts: ["一句提示词"] };

  it("「第一份产出」是那个口的第 1 份,「全部产出」是它的全部 2 份;文字产出不算", () => {
    const repeats = repeatsOf(outputRows(registry, "comfy", comfy));
    expect(Object.fromEntries(repeats)).toEqual({
      asset_id: { label: "图 · 预览图像", index: 1, whole: false, count: 1 },
      asset_ids: { label: "图 · 预览图像", index: null, whole: true, count: 2 },
    });
  });

  it("只出一张时「第一份产出」就是那一张", () => {
    const repeats = repeatsOf(outputRows(registry, "comfy", { image_9: ["img1"], asset_id: "img1", asset_ids: ["img1"] }));
    expect(repeats.get("asset_id")).toEqual({ label: "图 · 预览图像", index: 1, whole: true, count: 1 });
  });

  it("值里夹着别的东西、或者指向的不是上面的素材,就不算 —— 照原样摆值", () => {
    const repeats = repeatsOf(outputRows(registry, "comfy", { image_9: ["img1"], asset_ids: ["img1", 3], asset_id: "img9" }));
    expect(repeats.size).toBe(0);
  });

  it("节点卡片上的摘要也跳过那串 id,给真正的文字产出", () => {
    //: 出图的工作流「文字产出」是个空列表 —— 卡片上摆一个「[]」和摆一串 id 一样没用。
    const summary = outputSummary(registry, "comfy", { image_9: ["img1", "img2"], asset_id: "img1", asset_ids: ["img1", "img2"], texts: [] });
    expect(summary).toBeNull();
  });

  it("两个口各交各的不算重复", () => {
    expect(repeatsOf(outputRows(registry, "separate_audio", { vocals_asset_id: "a1", background_asset_id: "a2" })).size).toBe(0);
  });
});
