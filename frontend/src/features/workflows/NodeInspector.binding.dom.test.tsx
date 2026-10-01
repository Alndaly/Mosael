/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

/**
 * 一格换了值从哪来(手填 ↔ 接上游),依赖它的字段就失效了:换接了另一条时间线,手里那条轨道 id
 * 不在新时间线上 —— 两格各自有值、界面看着正常,跑起来才报「这条时间线上没有那条轨道」。
 */

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReactFlowProvider } from "@xyflow/react";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
});

const META = {
  type: "append_to_timeline",
  label: "放进时间线",
  description: "",
  category: "",
  config: {
    sequence_id: { type: "template", label: "时间线" },
    track_id: { type: "template", label: "轨道", depends_on: "sequence_id" },
    at: { type: "number", label: "位置" },
  },
  outputs: [],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

function renderInspector(node: WorkflowGraph["nodes"][number], edges: WorkflowGraph["edges"] = []) {
  const onApplyGraph = vi.fn();
  const graph = { nodes: [{ id: "tl", type: "timeline_create", config: {} }, node], edges } as WorkflowGraph;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node}
            meta={META}
            graph={graph}
            registry={new Map([[META.type, META]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={onApplyGraph}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const modeToggle = (key: string) =>
    document.querySelector<HTMLButtonElement>(`[data-field-key="${key}"] button[title="wfInputModeHint"]`)!;
  const applied = () => (onApplyGraph.mock.calls.at(-1)![0] as WorkflowGraph).nodes.find((one) => one.id === node.id)!;
  return { onApplyGraph, modeToggle, applied };
}

it("时间线拨到「接上游」、还没挑来源:值还是手填的那个,轨道不清", () => {
  //: 此前一拨开关就清:可这时还没有数据边,运行时用的仍是手填的时间线,那条轨道仍然对。
  const { modeToggle, applied } = renderInspector({
    id: "n1",
    type: META.type,
    config: { sequence_id: "seq-old", track_id: "trk-old", at: 2 },
  });
  fireEvent.click(modeToggle("sequence_id"));
  expect(applied().inputs).toEqual(["sequence_id"]);
  expect(applied().config).toEqual({ sequence_id: "seq-old", track_id: "trk-old", at: 2 });
});

it("时间线从接着上游改回手填:数据边删掉,依赖它的轨道也清掉(值从哪来真的换了)", () => {
  const { modeToggle, onApplyGraph, applied } = renderInspector(
    { id: "n1", type: META.type, inputs: ["sequence_id"], config: { sequence_id: "", track_id: "trk-old" } },
    [{ id: "d1", source: "tl", target: "n1", kind: "data", source_output: "sequence_id", target_input: "sequence_id" }],
  );
  fireEvent.click(modeToggle("sequence_id"));
  expect(applied().inputs).toEqual([]);
  expect(applied().config).toEqual({ sequence_id: "", track_id: "" });
  expect((onApplyGraph.mock.calls.at(-1)![0] as WorkflowGraph).edges).toEqual([]);
});

it("拨回手填时本来就没接上数据边:只是收起开关,轨道不清", () => {
  const { modeToggle, applied } = renderInspector({
    id: "n1",
    type: META.type,
    inputs: ["sequence_id"],
    config: { sequence_id: "seq-old", track_id: "trk-old" },
  });
  fireEvent.click(modeToggle("sequence_id"));
  expect(applied().inputs).toEqual([]);
  expect(applied().config).toEqual({ sequence_id: "seq-old", track_id: "trk-old" });
});

const CODE_META = {
  type: "code",
  label: "代码",
  description: "",
  category: "",
  config: { code: { type: "code", label: "代码", required: true }, input: { type: "template", label: "入参" } },
  outputs: ["output"],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

it("代码字段接了上游(后端拒跑):检查器给一个断开的入口,点了删掉那条数据边", () => {
  //: 代码字段不给「接上游」开关(上游的值会整段变成代码),于是已经接上的(智能体改的、旧图)连断都断不开。
  const node = { id: "c1", type: "code", inputs: ["code"], config: { code: "" } };
  const graph = {
    nodes: [{ id: "llm-1", type: "llm", config: {} }, node],
    edges: [{ id: "d1", source: "llm-1", target: "c1", kind: "data", source_output: "text", target_input: "code" }],
  } as WorkflowGraph;
  const onApplyGraph = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node}
            meta={CODE_META}
            graph={graph}
            registry={new Map([[CODE_META.type, CODE_META]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={onApplyGraph}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const unbind = document.querySelector<HTMLButtonElement>('[data-field-key="code"] [data-code-bound]');
  expect(unbind?.textContent).toContain("wfCodeFieldBoundUnbind");
  fireEvent.click(unbind!);
  const next = onApplyGraph.mock.calls.at(-1)![0] as WorkflowGraph;
  expect(next.edges).toEqual([]);
  expect(next.nodes.find((one) => one.id === "c1")!.inputs).toEqual([]);
});

it("失效引用不查代码字段:代码里的 {{…}} 是字面文字;入参里的照查", () => {
  //: 代码不插值(后端 code_fields)。此前检查器把代码里的 {{…}} 当引用,报「引用了已删除的节点」,
  //: 还给一个「重新指向」去改写用户的代码 —— 就绪清单却(正确地)不报,两处说的不是一件事。
  const node = { id: "c1", type: "code", config: { code: "print('{{gone.code}}')", input: "{{gone.input}}" } };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node}
            meta={CODE_META}
            graph={{ nodes: [node], edges: [] } as WorkflowGraph}
            registry={new Map([[CODE_META.type, CODE_META]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const stale = [...document.querySelectorAll("code.line-through")].map((one) => one.textContent);
  expect(stale).toEqual(["{{gone.input}}"]);
});
