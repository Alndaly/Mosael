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
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    params: {
      type: "object", label: "启动参数", editor: "start_params", required_list: "required_params", options_map: "param_options",
    },
    required_params: { type: "list", label: "必填参数", edited_by: "params" },
    param_options: { type: "object", label: "选项", edited_by: "params" },
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


// ---- 选项参数:只能从几项里选的那一行,默认值栏是下拉 ----

const SOURCES = [
  { value: "browser", label: "内嵌浏览器", description: "不用配置" },
  { value: "tikhub", label: "TikHub", description: "需安装 TikHub 插件并配置密钥", requires: "tikhub_account" },
];

/** 模板前置条件的状态:TikHub 这一项此刻缺。别的请求照旧回空清单。 */
function tikhubMissing() {
  vi.stubGlobal("fetch", async (url: string) =>
    new Response(
      JSON.stringify(String(url).includes("/templates/checks") ? [{ check: "tikhub_account", status: "missing" }] : []),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
}

it("选项参数:默认值栏是下拉(不是文本框);选一项存成那个值,选中那一项的说明写在下面", async () => {
  const { row, last } = renderStart({
    params: { account_link: "", data_source: "" }, required_params: ["data_source"], param_options: { data_source: SOURCES },
  });
  expect(within(row(1)).queryByRole("textbox", { name: "wfStartParamDefaultOf" })).toBeNull();
  const user = userEvent.setup();
  await user.click(within(row(1)).getByRole("combobox", { name: "wfStartParamDefaultOf" }));
  await user.click(await screen.findByRole("option", { name: /内嵌浏览器/ }));
  expect(last()).toEqual({
    params: { account_link: "", data_source: "browser" }, required_params: ["data_source"], param_options: { data_source: SOURCES },
  });
  expect(row(1).querySelector("[data-start-param-option-note]")?.textContent).toBe("不用配置");
});

it("必填、还没选:那一行标「必填,还没选」", () => {
  const { row } = renderStart({ params: { data_source: "" }, required_params: ["data_source"], param_options: { data_source: SOURCES } });
  expect(row(0).querySelector("[data-start-param-notice]")?.textContent).toBe("wfStartParamPickRequired");
});

it("要的东西没备好的那一项在下拉里标「未就绪」但照样能选;选中它那一行说清运行前会被拦", async () => {
  tikhubMissing();
  try {
    const { row, last } = renderStart({ params: { data_source: "" }, required_params: [], param_options: { data_source: SOURCES } });
    const user = userEvent.setup();
    await user.click(within(row(0)).getByRole("combobox", { name: "wfStartParamDefaultOf" }));
    const tikhub = await screen.findByRole("option", { name: /TikHub · wfStartParamOptionNotReady/ });
    expect(screen.getByRole("option", { name: /内嵌浏览器/ }).textContent).not.toContain("wfStartParamOptionNotReady");
    await user.click(tikhub);
    expect((last().params as Config).data_source).toBe("tikhub");
    await waitFor(() =>
      expect(row(0).querySelector("[data-start-param-notice]")?.textContent).toBe("wfStartParamOptionUnavailable"),
    );
  } finally {
    vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
  }
});

it("值不在选项里(旧图手填的「TikHub」):就地说,运行前会被拦", () => {
  const { row } = renderStart({ params: { data_source: "TikHub" }, required_params: [], param_options: { data_source: SOURCES } });
  expect(row(0).querySelector("[data-start-param-notice]")?.getAttribute("data-start-param-notice")).toBe("not-an-option");
});

it("改名:选项跟着那一行走;删行:选项一起没了", () => {
  const { row, last } = renderStart({
    params: { source: "browser", tone: "" }, required_params: ["source"], param_options: { source: SOURCES },
  });
  act(() => fireEvent.change(within(row(0)).getByRole("textbox", { name: "wfStartParamName" }), { target: { value: "data_source" } }));
  expect(last()).toEqual({
    params: { data_source: "browser", tone: "" }, required_params: ["data_source"], param_options: { data_source: SOURCES },
  });
  act(() => fireEvent.click(within(row(0)).getByRole("button", { name: "wfStartParamRemove" })));
  expect(last()).toEqual({ params: { tone: "" }, required_params: [], param_options: {} });
});
