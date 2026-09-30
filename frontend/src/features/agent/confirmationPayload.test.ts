import { describe, expect, it } from "vitest";

import { guessLanguage, payloadFields } from "@/features/agent/confirmationPayload";

describe("确认卡的参数表", () => {
  it("插件工具的载荷:摊开 arguments 的字段,卡上别处说过的事实和机器 id 不列", () => {
    const fields = payloadFields({
      arguments: { code: "import numpy as np\nfrom manim import *", fps: 30, filename: "scene.mp4" },
      instance_id: "0f3c…",
      tool_name: "custom_animation",
      tool_label: "Manim 自定义动画",
      connection: "Manim 教学动画",
      effects: "local-code",
    });
    expect(fields.map((one) => one.key)).toEqual(["fps", "filename", "code"]);
    expect(fields[2]).toMatchObject({ kind: "text", language: "python" });
  });

  it("多行字符串原样保留真实换行,不是转义过的 \\n", () => {
    const [code] = payloadFields({ code: "a = 1\nb = 2" });
    expect(code).toMatchObject({ kind: "text", text: "a = 1\nb = 2" });
  });

  it("短的在上、成块的在下,嵌套对象成小表,太深的交给 JSON 块", () => {
    const fields = payloadFields({
      prompt: "一只猫\n在屋顶上",
      model: "flux",
      options: { seed: 7 },
      graph: { nodes: [{ id: "n1", config: { code: "x" } }] },
      _names: ["内部"],
    });
    expect(fields.map((one) => [one.key, one.kind])).toEqual([
      ["model", "value"],
      ["prompt", "text"],
      ["options", "group"],
      ["graph", "group"],
    ]);
    const graph = fields[3];
    expect(graph.kind === "group" && graph.fields[0]).toMatchObject({ key: "nodes", kind: "data" });
  });

  it("短数组拼成一行,空字符串照样列出来", () => {
    expect(payloadFields({ clip_ids: ["a", "b"], title: "" })).toEqual([
      { kind: "value", key: "clip_ids", text: "a, b" },
      { kind: "value", key: "title", text: "" },
    ]);
  });
});

describe("长文本的语言", () => {
  it.each([
    ["code", "import os\nos.remove('x')", "python"],
    ["code", "print(1)", "python"],
    ["script", "const a = 1;\nexport default a", "javascript"],
    ["body", '{"a": 1}', "json"],
    ["markdown", "# 标题\n正文", "markdown"],
    ["prompt", "Update the timeline\nthen export", null],
    ["text", "一段很长的提示词", null],
  ])("%s: %s → %s", (key, text, language) => {
    expect(guessLanguage(key, text)).toBe(language);
  });
});
