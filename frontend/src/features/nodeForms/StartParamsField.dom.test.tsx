/** @vitest-environment jsdom */
/**
 * 开始节点的启动参数面板:一行一个参数(名字、默认值、必填),必填跟着那一行走。
 *
 * 此前下半是一个独立的「必填参数」文本框(手打逗号分隔的名字):同一个名字写两遍、打错没提示,改名删行之后那串字
 * 不跟着变。值那一格还是「值或上游输出」的下拉,而开始节点前面什么都没有。
 *
 * 走真的宿主(节点检查器)—— 它把改动交成一个 `config` 补丁,和存进图里的是同一份。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

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

const START = {
  type: "start",
  label: "开始",
  description: "",
  category: "",
  config: {
    params: { type: "object", label: "启动参数", editor: "start_params", required_list: "required_params" },
    required_params: { type: "list", label: "必填参数", edited_by: "params" },
  },
  outputs: ["*params"],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

const LLM = {
  type: "llm",
  label: "LLM",
  description: "",
  category: "",
  config: { prompt: { type: "template" }, extra: { type: "object", label: "映射" } },
  outputs: ["text"],
  output_types: { text: "text" },
  output_labels: {},
} as unknown as WorkflowNodeType;

type Config = Record<string, unknown>;

/** 宿主:把检查器交来的补丁落到节点上(和编辑器 applyGraph 同一个意思),记下每一次存的样子。 */
function renderStart(config: Config) {
  const saved: Config[] = [];
  function Host() {
    const [node, setNode] = React.useState({ id: "start", type: "start", config });
    const upstream = { id: "llm-1", type: "llm", config: {} };
    return (
      <NodeInspector
        node={node}
        meta={START}
        graph={{ nodes: [node, upstream], edges: [] } as WorkflowGraph}
        registry={new Map([[START.type, START], [LLM.type, LLM]])}
        workspaceId="w1"
        onChange={(patch) => {
          const next = { ...node, ...patch } as typeof node;
          saved.push(next.config);
          setNode(next);
        }}
        onApplyGraph={vi.fn()}
      />
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <Host />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  const panel = () => document.querySelector<HTMLElement>("[data-start-params]")!;
  const row = (index: number) => panel().querySelector<HTMLElement>(`[data-start-param-row="${index}"]`)!;
  return { saved, last: () => saved[saved.length - 1], panel, row };
}

it("每一行自带「必填」开关(有可访问名);勾上 → 存成参数名的列表;没有单独的必填文本框", () => {
  const { last, panel } = renderStart({ params: { account_link: "", data_source: "auto" }, required_params: [] });
  expect(document.querySelector('[data-field-key="required_params"]')).toBeNull();
  const toggles = within(panel()).getAllByRole("checkbox");
  expect(toggles.map((one) => one.getAttribute("aria-label"))).toEqual(["wfStartParamRequiredOf", "wfStartParamRequiredOf"]);
  act(() => fireEvent.click(toggles[0]));
  expect(last()).toEqual({ params: { account_link: "", data_source: "auto" }, required_params: ["account_link"] });
  act(() => fireEvent.click(toggles[1]));
  expect(last().required_params).toEqual(["account_link", "data_source"]);
  act(() => fireEvent.click(toggles[0]));
  expect(last().required_params).toEqual(["data_source"]);
});

it("改名:必填跟着那一行走;删行:必填跟着没了", () => {
  const { last, row } = renderStart({ params: { acount_link: "", tone: "轻松" }, required_params: ["acount_link"] });
  const name = within(row(0)).getByRole("textbox", { name: "wfStartParamName" });
  act(() => fireEvent.change(name, { target: { value: "account_link" } }));
  expect(last()).toEqual({ params: { account_link: "", tone: "轻松" }, required_params: ["account_link"] });
  act(() => fireEvent.click(within(row(0)).getByRole("button", { name: "wfStartParamRemove" })));
  expect(last()).toEqual({ params: { tone: "轻松" }, required_params: [] });
});

it("值那一格只是默认值:占位「默认值(可空)」,不是能挑上游输出的下拉", () => {
  const { panel, row, last } = renderStart({ params: { topic: "" }, required_params: [] });
  expect(within(panel()).queryByRole("combobox")).toBeNull();
  const value = within(row(0)).getByRole("textbox", { name: "wfStartParamDefaultOf" });
  expect(value.getAttribute("placeholder")).toBe("wfStartParamDefaultPlaceholder");
  act(() => fireEvent.change(value, { target: { value: "面馆" } }));
  expect(last()).toEqual({ params: { topic: "面馆" }, required_params: [] });
  //: 开始节点上不出「值或上游输出」那种映射控件(别的节点上照旧是它,见 MapField 的测试)。
  expect(screen.queryByText("wfMapValue")).toBeNull();
});

it("必填且没有默认值的行当场标出「运行时要填」;有默认值的不标", () => {
  const { row } = renderStart({ params: { topic: "", tone: "轻松" }, required_params: ["topic", "tone"] });
  expect(row(0).querySelector("[data-start-param-notice]")?.textContent).toBe("wfStartParamAskAtRun");
  expect(row(1).querySelector("[data-start-param-notice]")).toBeNull();
});

it("名字空着、和前面重名的行就地提示,都不存", () => {
  const { panel, row, last } = renderStart({ params: { topic: "" }, required_params: ["topic"] });
  act(() => fireEvent.click(within(panel()).getByText("wfMapAdd")));
  act(() => fireEvent.change(within(row(1)).getByRole("textbox", { name: "wfStartParamDefaultOf" }), { target: { value: "x" } }));
  expect(row(1).querySelector("[data-start-param-notice]")?.textContent).toBe("wfStartParamNameEmpty");
  act(() => fireEvent.change(within(row(1)).getByRole("textbox", { name: "wfStartParamName" }), { target: { value: "topic" } }));
  expect(row(1).querySelector("[data-start-param-notice]")?.textContent).toBe("wfStartParamNameDuplicate");
  expect(within(row(1)).getByRole("textbox", { name: "wfStartParamName" }).getAttribute("aria-invalid")).toBe("true");
  //: 同名时先出现的那行算数:存下去的还是第一行。
  expect(last()).toEqual({ params: { topic: "" }, required_params: ["topic"] });
});
