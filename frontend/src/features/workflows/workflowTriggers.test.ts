/**
 * 触发器那几件纯的:关键词怎么切、入参怎么映射、开始节点的参数怎么取、事件好坏怎么判。
 * 面板(dialog)只负责画,规则都在这里,所以它们各自单独测。
 */
import { describe, expect, it } from "vitest";

import {
  eventTone,
  formatKeywords,
  parseKeywords,
  startParamNamesOf,
  triggerSummary,
  withParamMapping,
} from "./workflowTriggers";

describe("关键词", () => {
  it("中英逗号和换行都算分隔,空的不留", () => {
    expect(parseKeywords("成片, 配音\n发布,, ")).toEqual(["成片", "配音", "发布"]);
    expect(parseKeywords("")).toEqual([]);
  });

  it("存回输入框时用同一种写法", () => {
    expect(formatKeywords(["a", "b"])).toBe("a, b");
  });
});

describe("入参映射", () => {
  it("选了哪一格就写那一格的占位符", () => {
    expect(withParamMapping({}, "asset_id", "{{trigger.asset_id}}")).toEqual({ asset_id: "{{trigger.asset_id}}" });
  });

  it("改选另一格是替换,不是又加一条", () => {
    expect(withParamMapping({ asset_id: "{{trigger.asset_id}}" }, "asset_id", "{{trigger.text}}")).toEqual({
      asset_id: "{{trigger.text}}",
    });
  });

  it("不传 = 把这一格删掉(不是存一个空串)", () => {
    expect(withParamMapping({ asset_id: "{{trigger.asset_id}}", text: "x" }, "asset_id", null)).toEqual({ text: "x" });
  });
});

describe("开始节点的参数", () => {
  it("按图取名字,顺序照声明", () => {
    const graph = { nodes: [{ id: "start", type: "start", config: { params: { topic: "", brief: "" } } }] };
    expect(startParamNamesOf(graph)).toEqual(["topic", "brief"]);
  });

  it("没有开始节点、图不是对象,都给空表(不抛)", () => {
    expect(startParamNamesOf({ nodes: [] })).toEqual([]);
    expect(startParamNamesOf(null)).toEqual([]);
    expect(startParamNamesOf({ nodes: [{ id: "t", type: "template" }] })).toEqual([]);
  });
});

describe("事件那一行的好坏", () => {
  it("五档状态各有各的语气", () => {
    expect(eventTone("started")).toBe("ok");
    expect(eventTone("throttled")).toBe("warn");
    expect(eventTone("refused")).toBe("bad");
    expect(eventTone("failed")).toBe("bad");
    expect(eventTone("skipped")).toBe("muted");
    //: 认不出的照走"没什么可说",不惊慌。
    expect(eventTone("something-new")).toBe("muted");
  });
});

describe("摘要那一行", () => {
  it("认什么、在哪、限流多少,拼成一句", () => {
    const trigger = {
      message_types: ["media", "text"],
      bot_id: "bot1",
      chat_id: "oc_1",
      keywords: ["成片"],
      max_runs_per_minute: 6,
    } as never;
    expect(triggerSummary(trigger, (kind) => kind.toUpperCase(), "ANY")).toBe(
      "MEDIA / TEXT  ·  bot1 · oc_1  ·  成片  ·  6/min",
    );
  });

  it("没绑机器人时说「任意」", () => {
    const trigger = {
      message_types: ["text"],
      bot_id: "",
      chat_id: "",
      keywords: [],
      max_runs_per_minute: 3,
    } as never;
    expect(triggerSummary(trigger, (kind) => kind, "ANY")).toBe("text  ·  ANY  ·  3/min");
  });
});
