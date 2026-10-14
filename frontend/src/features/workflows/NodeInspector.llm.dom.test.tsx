/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 大模型节点的**输出格式 + JSON Schema 收在「高级」档**(维护者拍板:JSON 是给下游按字段取的微调,不占基础档
 * 第一眼);采样参数、Schema 名称、严格与否也在高级。回归钉:llm 的高级项全由专区渲染、被剔出通用
 * advancedSpecs —— 「高级」这一档本身必须仍然出现(此前因此整个高级档丢了,维护者以为这个节点没有 JSON 模式)。
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

describe("大模型节点的高级档", () => {
  it("条上有「高级」这一档(回归:专区的高级项被剔出 advancedSpecs,档本身不能丢)", () => {
    const view = renderLlm({ response_format: "text" });
    expect(view.container.textContent).toContain("wfaConfig");
    expect(view.container.textContent).toContain("wfAdvanced");
  });

  it("输出格式在高级档:默认停在参数档看不见,切过去才有,底下说清下游怎么取", () => {
    const view = renderLlm({ response_format: "json_object" });
    // 默认停在参数档:输出格式不在
    expect(view.container.querySelector("[data-llm-response-format]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "wfAdvanced" }));
    const format = view.container.querySelector("[data-llm-response-format]");
    expect(format).not.toBeNull();
    expect(format!.textContent).toContain("wfLlmResponseFormat");
    expect(format!.textContent).toContain("wfLlmResponseJsonHint");
    // 不限结构时没有 Schema 要填
    expect(view.container.textContent).not.toContain("wfLlmJsonSchema");
  });

  it("选「按 Schema」:Schema 编辑框、名字、严格与否都在高级档", () => {
    const view = renderLlm({ response_format: "json_schema", json_schema: { type: "object", properties: {} } });
    fireEvent.click(screen.getByRole("button", { name: "wfAdvanced" }));
    expect(view.container.textContent).toContain("wfLlmJsonSchema");
    expect(view.container.textContent).toContain("wfLlmResponseSchemaHint");
    expect(view.container.textContent).toContain("wfLlmJsonSchemaName");
    expect(view.container.textContent).toContain("wfLlmJsonStrict");
  });
});
