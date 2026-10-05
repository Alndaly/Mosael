import { describe, expect, it } from "vitest";

import type { GenerationOption } from "@/api/client";
import { messages, type MessageKey } from "@/app/messages";
import { acceptsDataEdge, inputPortName, inputPortPath, outputPortName, type PortRegistry } from "@/features/workflows/portNames";

//: 只放这几条用例要的声明,形状和节点目录一样(名字已按界面语言翻好)。
const TYPES: Record<string, ReturnType<PortRegistry["get"]>> = {
  ai_generate: {
    config: {
      prompt: { type: "template", label: "提示词" },
      parameters: { type: "object", editor: "map", label: "生成参数", entry_labels: "generation_parameters" },
      source_assets: { type: "template", lines: true, label: "输入素材", entry_labels: "source_roles" },
    },
    output_labels: { asset_id: "素材", asset_ids: "素材列表" },
  },
  llm: {
    config: { json_schema: { type: "object", editor: "json", label: "JSON Schema" } },
    output_labels: { json: "JSON" },
  },
  output: {
    config: { values: { type: "object", editor: "map", label: "具名输出" } },
    output_labels: { output: "对外输出" },
    port_maps: { values: { input: "values", output: "output" } },
  },
  start: { config: { params: { type: "object", editor: "start_params", label: "参数" } }, output_labels: { "*params": "参数" } },
  "plugin.deck.slides": {
    config: {
      steps: {
        type: "list",
        editor: "items",
        label: "讲解步骤",
        fields: { title: { type: "text", label: "标题" }, body: { type: "text", label: "正文" } },
      },
      style: { type: "object", editor: "fields", label: "版式", fields: { width: { type: "number", label: "宽度" } } },
    },
  },
};
const registry: PortRegistry = { get: (type) => TYPES[type] };
const zh = (key: MessageKey) => messages["zh-CN"][key];
const context = { registry, t: zh };

describe("引用落在哪个输入口", () => {
  it("往下只走到表单能单独填的那一格", () => {
    //: 原始 JSON 框:里面写在哪一层都是这一格。
    expect(inputPortPath(registry, "llm", ["json_schema", "properties", "shots", "description"])).toBe("json_schema");
    expect(inputPortPath(registry, "ai_generate", ["parameters", "aspect_ratio"])).toBe("parameters.aspect_ratio");
    expect(inputPortPath(registry, "ai_generate", ["source_assets", "0"])).toBe("source_assets.0");
    expect(inputPortPath(registry, "ai_generate", ["prompt"])).toBe("prompt");
    //: 一项是一块结构的,每项的每一格一个口。
    expect(inputPortPath(registry, "plugin.deck.slides", ["steps", "1", "title", "x"])).toBe("steps.1.title");
    //: 目录里没有的一格(插件没装):整格一个口。
    expect(inputPortPath(registry, "plugin.missing", ["input", "a", "b"])).toBe("input");
  });
});

describe("哪些口能接数据边", () => {
  it("和检查器的「接上游」同一个判据:一整格要收得下上游的值;一格里的一项各自收得下", () => {
    expect(acceptsDataEdge(registry, "ai_generate", "prompt")).toBe(true);
    expect(acceptsDataEdge(registry, "ai_generate", "parameters.aspect_ratio")).toBe(true);
    expect(acceptsDataEdge(registry, "ai_generate", "source_assets.0")).toBe(true);
    expect(acceptsDataEdge(registry, "output", "values.note_id")).toBe(true);
    //: 原始 JSON 框整格一个口:口是给引用提示线接的,拖一条数据边上去会把整份 JSON 换掉。
    expect(acceptsDataEdge(registry, "llm", "json_schema")).toBe(false);
    expect(acceptsDataEdge(registry, "ai_generate", "parameters")).toBe(false);
  });
});

describe("输入口叫什么", () => {
  const node = {
    type: "ai_generate",
    config: {
      parameters: { aspect_ratio: "{{input.aspect_ratio}}", fps: "{{input.fps}}" },
      source_assets: ["{{a.asset_id}}:first_frame", "{{b.asset_id}}:reference_image", "{{c.asset_id}}:reference_image", "{{d.asset_ids}}"],
    },
  };

  it("一整格是节点目录给的名字", () => {
    expect(inputPortName(context, node, "prompt")).toBe("提示词");
  });

  it("生成参数叫检查器那一格的名字,不是键名", () => {
    expect(inputPortName(context, node, "parameters.aspect_ratio")).toBe("画面比例");
  });

  it("模型自己声明的参数用它声明的名字;说不出来的才是键", () => {
    const model = {
      capabilities: { parameter_keys: ["fps"], parameter_schema: { fps: { type: "integer", title: "帧率(插件)" } } },
    } as unknown as GenerationOption;
    expect(inputPortName({ ...context, generationModel: () => model }, node, "parameters.fps")).toBe("帧率(插件)");
    expect(inputPortName(context, node, "parameters.fps")).toBe("fps");
  });

  it("输入素材的一行叫它的角色;同一角色几行带上第几个;没写角色的是「输入素材 n」", () => {
    expect(["0", "1", "2", "3"].map((index) => inputPortName(context, node, `source_assets.${index}`))).toEqual([
      "首帧",
      "参考图 1",
      "参考图 2",
      "输入素材 4",
    ]);
  });

  it("键值映射的键是用户起的名字,原样;插件结构里的一格叫它声明的名字", () => {
    expect(inputPortName(context, { type: "output", config: {} }, "values.note_id")).toBe("note_id");
    const slides = { type: "plugin.deck.slides", config: { steps: [{ title: "{{a.text}}" }] } };
    expect(inputPortName(context, slides, "steps.0.title")).toBe("讲解步骤 1 · 标题");
    expect(inputPortName(context, slides, "style.width")).toBe("宽度");
  });
});

describe("输出口叫什么", () => {
  it("目录给的名字;按配置展开的、开始参数是用户起的键;JSON 里的字段跟在后面", () => {
    expect(outputPortName(registry, { type: "ai_generate" }, "asset_ids")).toBe("素材列表");
    expect(outputPortName(registry, { type: "output" }, "output.note_id")).toBe("note_id");
    expect(outputPortName(registry, { type: "output" }, "output")).toBe("对外输出");
    expect(outputPortName(registry, { type: "start" }, "topic")).toBe("topic");
    expect(outputPortName(registry, { type: "llm" }, "json.verdict")).toBe("JSON · verdict");
  });
});
