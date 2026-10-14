/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 大模型节点的**输出格式**在参数档,不在高级里:维护者翻了一圈以为这个节点没有 JSON 模式。选「按 Schema」时
 * Schema 编辑框跟着出现在参数档;Schema 的名字、严格与否这类微调留在高级。
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

const LLM: WorkflowNodeType = {
  type: "llm",
  label: "llm",
  description: "",
  category: "",
  config: {
    prompt: { type: "template", required: true },
    response_format: { type: "string", options: ["text", "json_object", "json_schema"] },
    json_schema: { type: "object" },
    json_schema_name: { type: "template", advanced: true },
    json_schema_strict: { type: "string", options: ["true", "false"], advanced: true },
    temperature: { type: "number", advanced: true },
  },
  outputs: ["text", "json", "response_format_used"],
  output_types: {},
  output_labels: {},
  plugin_name: "",
  tool_name: "",
};

function renderLlm(config: Record<string, unknown>) {
  const node = { id: "ask", type: "llm", config: { prompt: "写三个标题", ...config } };
  const graph: WorkflowGraph = { nodes: [node], edges: [] };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={LLM}
            graph={graph}
            registry={new Map([["llm", LLM]])}
            workspaceId="w1"
            onChange={vi.fn()}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("大模型节点的输出格式", () => {
  it("一打开就在参数档,底下说清下游怎么取", () => {
    const view = renderLlm({ response_format: "json_object" });
    const format = view.container.querySelector("[data-llm-response-format]");
    expect(format).not.toBeNull();
    expect(format!.textContent).toContain("wfLlmResponseFormat");
    expect(format!.textContent).toContain("wfLlmResponseJsonHint");
    // 不限结构时没有 Schema 要填
    expect(view.container.textContent).not.toContain("wfLlmJsonSchema");
  });

  it("选「按 Schema」:Schema 编辑框就在参数档,名字和严格与否不在这里", () => {
    const view = renderLlm({ response_format: "json_schema", json_schema: { type: "object", properties: {} } });
    expect(view.container.textContent).toContain("wfLlmJsonSchema");
    expect(view.container.textContent).toContain("wfLlmResponseSchemaHint");
    expect(view.container.textContent).not.toContain("wfLlmJsonSchemaName");
    expect(view.container.textContent).not.toContain("wfLlmJsonStrict");
  });
});
