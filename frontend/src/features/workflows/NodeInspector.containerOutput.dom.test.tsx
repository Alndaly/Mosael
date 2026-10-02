/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import type { Editor } from "@tiptap/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

/**
 * 循环 / 子图自己的 output、条件循环的 condition 在**体跑完之后**拿体的上下文求值:能插的是体里
 * 节点的输出。此前 @ 菜单列的是容器外面的上游 —— 选进去的引用运行时一律是空的。
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
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
});

const meta = (type: string, rest: Partial<WorkflowNodeType>) =>
  ({ type, label: type, description: "", category: "", config: {}, outputs: [], output_types: {}, output_labels: {}, ...rest }) as unknown as WorkflowNodeType;

const REGISTRY = new Map([
  ["upstream", meta("upstream", { outputs: ["text"] })],
  ["translate", meta("translate", { outputs: ["translated"] })],
  ["condition", meta("condition", { outputs: ["result"] })],
  [
    "loop_while",
    meta("loop_while", {
      config: {
        body: { type: "graph" },
        condition: { type: "template", label: "条件" },
        output: { type: "template", label: "输出" },
      },
      outputs: ["results"],
      body_scope: { loop: ["index"] },
    } as Partial<WorkflowNodeType>),
  ],
]);

const LOOP = {
  id: "loop",
  type: "loop_while",
  config: {
    body: {
      nodes: [
        { id: "tr", type: "translate", config: {} },
        { id: "check", type: "condition", config: {} },
      ],
      edges: [],
    },
  },
};
const GRAPH = {
  nodes: [{ id: "up", type: "upstream", config: {} }, LOOP],
  edges: [{ id: "e", source: "up", target: "loop" }],
} as WorkflowGraph;

async function suggestionsIn(fieldKey: string): Promise<string> {
  const editor = await waitFor(() => {
    const dom = document.querySelector(`[data-field-key="${fieldKey}"] .ProseMirror`) as (HTMLElement & { editor?: Editor }) | null;
    expect(dom?.editor).toBeTruthy();
    return dom!.editor!;
  });
  act(() => {
    editor.commands.focus("end");
    editor.commands.insertContent("@");
  });
  return waitFor(() => {
    const menu = document.querySelector("[data-suggestion-menu]");
    expect(menu?.textContent).toBeTruthy();
    return menu!.textContent!;
  });
}

function renderLoop() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={LOOP}
            meta={REGISTRY.get("loop_while")!}
            graph={GRAPH}
            registry={REGISTRY}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

it("条件循环的 condition:@ 列的是体里节点的输出和 loop.index,不是容器外面的上游", async () => {
  renderLoop();
  const listed = await suggestionsIn("condition");
  //: 菜单里摆的是引用的样子(节点 · 输出),和插进去之后那枚标签同一个名字。
  expect(listed).toContain("check · result");
  expect(listed).toContain("tr · translated");
  expect(listed).toContain("loop · index");
  expect(listed).not.toContain("up · text");
});
