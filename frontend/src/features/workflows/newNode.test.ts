import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { newNode } from "@/features/workflows/useWorkflowCanvasEdits";

/**
 * 「添加节点」放下的节点叫什么。
 *
 * 维护者:同一张 ComfyUI 工作流,模型下拉里叫精简表单的标题「快速用krea2生图」,画布上的节点却叫「工作流 ·
 * krea2-text-2-image」。插件节点的名字是插件报的、会变 —— 加的时候写死了,标题改了它也不跟。
 */

const graph: WorkflowGraph = { nodes: [{ id: "start", type: "start", config: {}, position: { x: 100, y: 0 } }], edges: [] };

describe("添加节点", () => {
  it("插件节点不写死名字:画布、检查器、引用跟着插件此刻报的名字走", () => {
    const node = newNode(graph, "plugin.dev.mosael.comfyui.wf_0ef16828a002", {
      label: "工作流 · krea2-text-2-image",
      config: { prompt: { type: "template" } },
    });
    expect("name" in node).toBe(false);
    expect(node).toMatchObject({ id: "plugin-dev-mosael-comfyui-wf-0ef16828a002-1", config: { prompt: "" } });
  });

  it("内置节点照旧写上它的名字", () => {
    const node = newNode(graph, "llm", { label: "大模型", config: { body: { type: "graph" }, map: { type: "object" } } });
    expect(node).toMatchObject({ id: "llm-1", name: "大模型", config: { body: { nodes: [], edges: [] }, map: {} } });
    expect(node.position).toEqual({ x: 340, y: 230 });
  });
});
