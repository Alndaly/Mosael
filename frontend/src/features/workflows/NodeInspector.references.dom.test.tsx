/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 「账号运营诊断」的交付节点:具名输出那张表里,引用一律显示成「节点 · 输出 · 子路径」—— 指向上游 JSON 输出里
 * **某个字段**的(`{{report.json.verdict}}`)此前不在下拉清单里,退回原样显示那串双括号。
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

function meta(type: string, config: Record<string, unknown>, outputs: string[], extra: Partial<WorkflowNodeType> = {}): WorkflowNodeType {
  return { type, label: type, description: "", category: "", config, outputs, output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", ...extra };
}

const REGISTRY = new Map<string, WorkflowNodeType>([
  ["start", meta("start", { params: { type: "object", editor: "start_params", required_list: "required_params" } }, ["*params"])],
  ["social_link", meta("social_link", { link: { type: "template" } }, ["platform", "id"], { output_labels: { platform: "平台", id: "编号" } })],
  [
    "llm",
    meta("llm", { prompt: { type: "template" }, json_schema: { type: "object", editor: "json" } }, ["text", "json"], {
      output_labels: { text: "文本", json: "JSON" },
      output_schema_from: { json: "json_schema" },
    }),
  ],
  ["note_create", meta("note_create", { title: { type: "template" } }, ["note_id"], { output_labels: { note_id: "笔记" } })],
  ["output", meta("output", { values: { type: "object", editor: "map", label: "具名输出" } }, [])],
]);

const OUTPUT = {
  id: "output",
  type: "output",
  name: "交付诊断与数据",
  config: {
    values: {
      note_id: "{{save_note.note_id}}",
      verdict: "{{report.json.verdict}}",
      report: "{{report.json.report_markdown}}",
      platform: "{{link.platform}}",
      typo: "{{reprot.json.title}}",
    },
  },
};

const GRAPH: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", config: { params: { account_link: "" } } },
    { id: "link", type: "social_link", name: "认出平台和编号", config: { link: "{{start.account_link}}" } },
    {
      id: "report",
      type: "llm",
      name: "写运营诊断",
      config: {
        prompt: "诊断",
        json_schema: {
          type: "object",
          properties: { title: { type: "string" }, verdict: { type: "string" }, report_markdown: { type: "string" } },
        },
      },
    },
    { id: "save_note", type: "note_create", name: "存成笔记", config: { title: "{{report.json.title}}" } },
    OUTPUT,
  ],
  edges: [
    { id: "e1", source: "start", target: "link" },
    { id: "e2", source: "link", target: "report" },
    { id: "e3", source: "report", target: "save_note" },
    { id: "e4", source: "save_note", target: "output" },
  ],
};

function renderOutputNode() {
  const onChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={OUTPUT as never}
            meta={REGISTRY.get("output")!}
            graph={GRAPH}
            registry={REGISTRY}
            workspaceId="w1"
            onChange={onChange}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const values = document.querySelector<HTMLElement>('[data-field-key="values"]')!;
  return { onChange, values };
}

describe("具名输出里的引用", () => {
  it("一律显示成「节点 · 输出 · 子路径」,表里不出现双括号", () => {
    const { values } = renderOutputNode();
    const shown = within(values).getAllByRole("combobox").map((trigger) => trigger.textContent);
    expect(shown).toEqual([
      "存成笔记 · 笔记",
      "写运营诊断 · JSON · verdict",
      "写运营诊断 · JSON · report_markdown",
      "认出平台和编号 · 平台",
      "reprot · json · title",
    ]);
    expect(values.textContent).not.toContain("{{");
  });

  it("写错了的那一行是错误样式,并说出为什么", () => {
    const { values } = renderOutputNode();
    const [typo] = within(values).getAllByRole("combobox").slice(-1);
    expect(typo.querySelector("[data-ref-problem='node']")).not.toBeNull();
    expect(within(values).getByRole("alert").textContent).toBe("wfRefMissingNode");
    //: 别的行都指得到。
    expect(values.querySelectorAll("[data-ref-problem]")).toHaveLength(1);
  });

  it("新加一行能直接挑上游 JSON 里的字段(按 schema 列出),名字顺手起成字段名", async () => {
    const user = userEvent.setup();
    const { values, onChange } = renderOutputNode();
    await user.click(within(values).getByRole("button", { name: "wfMapAdd" }));
    const triggers = within(values).getAllByRole("combobox");
    await user.click(triggers.at(-1)!);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("写运营诊断 · JSON · title")).toBeTruthy();
    await user.click(within(listbox).getByText("写运营诊断 · JSON · title"));
    const [patch] = onChange.mock.calls.at(-1)!;
    expect(patch.config.values).toEqual({ ...OUTPUT.config.values, title: "{{report.json.title}}" });
  });
});
