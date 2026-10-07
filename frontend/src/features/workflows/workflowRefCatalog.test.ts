import { describe, expect, it } from "vitest";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import { refLabel } from "@/features/nodeForms/refCatalog";
import { workflowRefCatalog } from "@/features/workflows/workflowRefCatalog";

function meta(outputs: string[], extra: Partial<WorkflowNodeType> = {}): WorkflowNodeType {
  return { type: "", label: "", description: "", category: "", config: {}, outputs, plugin_name: "", tool_name: "", ...extra };
}

const registry = new Map<string, WorkflowNodeType>([
  ["start", meta(["*params"])],
  ["llm", meta(["text", "json"], { output_labels: { text: "文本", json: "JSON" }, output_schema_from: { json: "json_schema" } })],
  ["note_create", meta(["note_id"], { output_labels: { note_id: "笔记" } })],
  ["output", meta(["output"], { output_labels: { output: "对外输出" }, port_maps: { values: { input: "values", output: "output" } } })],
  ["plugin.dev.mosael.comfyui.wf_0ef16828a002", meta(["image_9"], { label: "工作流 · 快速用krea2生图", output_labels: { image_9: "图 · 预览图像" } })],
]);

//: 「账号运营诊断」那张图里交付节点引用的几处。
const graph: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", config: { params: { account_link: "", post_count: 30 } } },
    {
      id: "report",
      type: "llm",
      name: "写运营诊断",
      config: {
        json_schema: {
          type: "object",
          properties: {
            title: { type: "string" },
            verdict: { type: "string" },
            sections: { type: "object", properties: { summary: { type: "string" } } },
            items: { type: "array", items: { type: "object", properties: { name: { type: "string" } } } },
          },
        },
      },
    },
    { id: "web", type: "llm", config: {} },
    { id: "save_note", type: "note_create", name: "存成笔记", config: {} },
    { id: "deliver", type: "output", name: "交付", config: { values: { note_id: "{{save_note.note_id}}" } } },
    { id: "krea", type: "plugin.dev.mosael.comfyui.wf_0ef16828a002", config: {} },
  ],
  edges: [],
};

describe("引用长什么样", () => {
  const catalog = workflowRefCatalog({ graph, registry });

  it("节点的名字 · 输出的显示名 · 子路径;没起名的节点用 id,插件节点用插件报的名字", () => {
    expect(refLabel(catalog.look("report.json.verdict"))).toBe("写运营诊断 · JSON · verdict");
    expect(refLabel(catalog.look("save_note.note_id"))).toBe("存成笔记 · 笔记");
    expect(refLabel(catalog.look("web.text"))).toBe("web · 文本");
    //: 开始节点的输出就是它的参数。
    expect(catalog.look("start.post_count")).toEqual({ parts: ["start", "post_count"], problem: null });
    //: 具名输出的每一项是画布上的一个口,名字是那一项的键 —— 和口上写的一样(portNames.outputPortName)。
    expect(refLabel(catalog.look("deliver.output.note_id"))).toBe("交付 · note_id");
    //: 插件节点不把名字写死:没起名就是插件此刻报的名字(精简表单的标题),不是一串节点 id。
    expect(refLabel(catalog.look("krea.image_9"))).toBe("工作流 · 快速用krea2生图 · 图 · 预览图像");
  });

  it("指不到东西的说清为什么:没有这个节点,或者节点在、没有这个输出", () => {
    expect(catalog.look("reprot.json.verdict").problem).toEqual({ kind: "node", node: "reprot" });
    expect(catalog.look("report.jsno.verdict").problem).toEqual({ kind: "output", node: "写运营诊断", output: "jsno" });
    expect(catalog.look("start.nope").problem).toEqual({ kind: "output", node: "start", output: "nope" });
  });

  it("体里的作用域变量(循环的 item、传进来的 input)指得到;作用域里没有的字段指不到", () => {
    const body = workflowRefCatalog({ graph: { nodes: [], edges: [] }, registry, scopeVariables: ["{{loop.item}}", "{{loop.index}}", "{{input.topic}}"] });
    expect(body.look("loop.item.mode")).toEqual({ parts: ["loop", "item", "mode"], problem: null });
    expect(body.look("input.topic").problem).toBeNull();
    expect(body.look("input.style").problem).toEqual({ kind: "output", node: "input", output: "style" });
  });
});

describe("输出底下能挑的字段", () => {
  it("输出声明了结构写在哪一格:按那份 JSON Schema 列,往对象里走、不进数组", () => {
    const catalog = workflowRefCatalog({ graph, registry });
    expect(catalog.fields("report.json")).toEqual(["title", "verdict", "sections", "sections.summary", "items"]);
    //: 没声明结构的输出、已经是子路径的、不存在的节点:没有可列的。
    expect(catalog.fields("report.text")).toEqual([]);
    expect(catalog.fields("report.json.sections")).toEqual([]);
    expect(catalog.fields("ghost.json")).toEqual([]);
  });

  it("上次运行交回过对象的,按交回的键列", () => {
    const catalog = workflowRefCatalog({
      graph,
      registry,
      runOutputs: { web: { json: { account: { name: "某号", followers: "1.2万" }, posts: [{ title: "a" }], notes: "" } } },
    });
    expect(catalog.fields("web.json")).toEqual(["account", "account.name", "account.followers", "posts", "notes"]);
  });
});
