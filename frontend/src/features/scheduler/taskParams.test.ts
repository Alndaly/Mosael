/**
 * 定时任务带给工作流的参数:从开始节点读出要填哪几项、哪几项不填就跑不起来、存进任务的是什么(体检 UM-03)。
 */
import { describe, expect, it } from "vitest";

import { formValuesFrom, missingRequired, runParamsFrom, startParamsOf } from "./taskParams";

const GRAPH = {
  nodes: [
    { id: "pick", type: "asset", config: { asset_id: "" } },
    {
      id: "start",
      type: "start",
      config: {
        params: { product_name: "", product_brief: "", audience: "都市通勤女性", scene_count: 4, source: "browser" },
        required_params: ["product_name", "product_brief"],
        param_options: { source: [{ value: "browser", label: "内嵌浏览器" }, { value: "tikhub", label: "TikHub" }] },
      },
    },
  ],
  edges: [],
};

describe("startParamsOf", () => {
  it("按声明的顺序读出开始节点的参数、必填和选项;没有开始节点就是空的", () => {
    const specs = startParamsOf(GRAPH);
    expect(specs.map((spec) => spec.name)).toEqual(["product_name", "product_brief", "audience", "scene_count", "source"]);
    expect(specs.filter((spec) => spec.required).map((spec) => spec.name)).toEqual(["product_name", "product_brief"]);
    expect(specs.find((spec) => spec.name === "source")?.options).toEqual([
      { value: "browser", label: "内嵌浏览器" },
      { value: "tikhub", label: "TikHub" },
    ]);
    expect(specs.find((spec) => spec.name === "audience")?.options).toBeUndefined();
    expect(startParamsOf({ nodes: [{ id: "x", type: "llm", config: {} }] })).toEqual([]);
    expect(startParamsOf(undefined)).toEqual([]);
  });
});

describe("missingRequired", () => {
  it("必填、空着、开始节点里也没有默认值的,才算缺", () => {
    const specs = startParamsOf({
      nodes: [{ id: "start", type: "start", config: { params: { a: "", b: "有默认", c: "" }, required_params: ["a", "b"] } }],
    });
    expect(missingRequired(specs, { a: "", b: "", c: "" })).toEqual(["a"]);
    expect(missingRequired(specs, { a: "  ", b: "", c: "" })).toEqual(["a"]);
    expect(missingRequired(specs, { a: "毛衣", b: "", c: "" })).toEqual([]);
  });
});

describe("runParamsFrom / formValuesFrom", () => {
  it("只存填了的那几格;默认值是数字的,填数字就存数字", () => {
    const specs = startParamsOf(GRAPH);
    const params = runParamsFrom(specs, { product_name: " 羊毛开衫 ", product_brief: "灰色", audience: "", scene_count: "6", source: "tikhub" });
    expect(params).toEqual({ product_name: "羊毛开衫", product_brief: "灰色", scene_count: 6, source: "tikhub" });
    expect(runParamsFrom(specs, { scene_count: "很多" })).toEqual({ scene_count: "很多" });
  });

  it("表单回填存过的值,没存过的空着(占位里写默认值)", () => {
    const specs = startParamsOf(GRAPH);
    expect(formValuesFrom(specs, { product_name: "开衫", scene_count: 6 })).toEqual({
      product_name: "开衫",
      product_brief: "",
      audience: "",
      scene_count: "6",
      source: "",
    });
    expect(formValuesFrom(specs, undefined).product_name).toBe("");
  });
});
