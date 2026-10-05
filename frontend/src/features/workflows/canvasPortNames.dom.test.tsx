/** @vitest-environment jsdom */
/**
 * 画布卡片上的接点写的是检查器里那一格的名字,按界面语言。
 *
 * 现场是「商品图 → 模特上身图与短视频」循环体里的「把这一组动起来」:输入口读作 提示词 / aspect_ratio / resolution / 0,
 * 输出口是 素材 / 素材 / 生成任务。这里把官方模板那一层真画到画布上(节点目录是后端导出的快照,文案是真的中英文案表),
 * 读卡片上每个口旁边写的字。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { workflowPortNamer } from "@/features/workflows/portNames";
import { WORKFLOW_NODE_TYPES, type WorkflowNodeData } from "@/features/workflows/WorkflowNode";
import { toWorkflowFlowNodes, workflowPortPresentation } from "@/features/workflows/workflowCanvasModel";
import { builtinNodeCatalog, uiText, type CatalogLocale } from "@/test/nodeCatalog";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

const DIR = join(import.meta.dirname, "../../../../website/public/workflows");

/** 官方模板「商品图 → 模特上身图与短视频」的循环体(「把这一组动起来」住在里面)。 */
function loopBody(build: CatalogLocale): WorkflowGraph {
  const copy = JSON.parse(readFileSync(join(DIR, `product_on_model.${build}.mosael-workflow.json`), "utf8")) as { graph: WorkflowGraph };
  const loop = copy.graph.nodes.find((node) => node.id === "shoot_scenes")!;
  return loop.config!.body as WorkflowGraph;
}

/** 按画布的做法画出这一层(接点的名字和 useWorkflowDisplayNodes 同一条路),交回某个节点两侧口旁边写的字。 */
function drawnPortNames(graph: WorkflowGraph, locale: CatalogLocale, nodeId: string): { inputs: string[]; outputs: string[] } {
  const registry = builtinNodeCatalog(locale);
  const names = workflowPortNamer({ registry, t: uiText(locale) });
  const nodes = toWorkflowFlowNodes(graph, registry).map((node) => ({
    ...node,
    data: {
      ...node.data,
      ...workflowPortPresentation(graph.nodes.find((one) => one.id === node.id)!, node.data as WorkflowNodeData, registry, names),
    },
  }));
  const { container, unmount } = render(
    <QueryClientProvider client={new QueryClient()}>
      <ReactFlowProvider>
        <div style={{ width: 1200, height: 800 }}>
          <ReactFlow nodes={nodes} edges={[]} nodeTypes={WORKFLOW_NODE_TYPES} />
        </div>
      </ReactFlowProvider>
    </QueryClientProvider>,
  );
  const card = container.querySelector<HTMLElement>(`.react-flow__node[data-id="${nodeId}"]`)!;
  //: 每个数据接点和它的名字在同一行里。
  const side = (prefix: string) =>
    [...card.querySelectorAll<HTMLElement>(`.react-flow__handle[data-handleid^="${prefix}"]`)].map((handle) => handle.parentElement?.textContent ?? "");
  const found = { inputs: side("in:"), outputs: side("out:") };
  unmount();
  return found;
}

describe("「把这一组动起来」的接点", () => {
  it("中文界面:和检查器同名 —— 画面比例、分辨率、首帧;两样素材分得开", () => {
    expect(drawnPortNames(loopBody("zh"), "zh", "on_model_clip")).toEqual({
      inputs: ["提示词", "画面比例", "分辨率", "首帧"],
      outputs: ["素材", "素材列表", "生成任务"],
    });
  });

  it("英文界面:同样几个口,英文名字", () => {
    expect(drawnPortNames(loopBody("en"), "en", "on_model_clip")).toEqual({
      inputs: ["Prompt", "Aspect ratio", "Resolution", "First frame"],
      outputs: ["Media", "Media list", "Generation"],
    });
  });

  it("名字跟着界面语言走,不跟着模板是哪种语言建的", () => {
    expect(drawnPortNames(loopBody("zh"), "en", "on_model_clip")).toEqual(drawnPortNames(loopBody("en"), "en", "on_model_clip"));
  });

  it("同一层「出这一组的模特上身图」:参考图那一行叫「参考图」,不叫 0", () => {
    expect(drawnPortNames(loopBody("zh"), "zh", "on_model").inputs).toEqual(["提示词", "参考图"]);
  });
});
