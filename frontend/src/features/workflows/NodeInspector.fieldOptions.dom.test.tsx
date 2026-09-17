/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 字段选项由后端声明从哪来(`options_from`),面板对所有这种字段一视同仁。
 *
 * 此前语音节点的「引擎 / 音色」是面板按节点类型写死的特例:两个音色键按引擎显示其一,
 * 顺序还一前一后,换引擎时音色那一格上下跳 —— 看起来就是两个音色框(用户报过)。
 * 这里用的节点类型名是**假的**,正是为了钉住"面板不认识具体节点"。
 */

//: NodeToolbar 只负责把面板贴到画布上的节点旁边 —— 那要一张真画布、真节点尺寸,和这里
//: 要验的事无关。换成原地渲染。
vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReactFlowProvider } from "@xyflow/react";

import { TooltipProvider } from "@/components/ui/tooltip";

import { NodeInspector } from "@/features/workflows/WorkflowsView";
import type { WorkflowNodeType } from "@/api/client";

beforeAll(() => {
  // Radix 的 Select 在打开时要 ResizeObserver,jsdom 没有。
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const META = {
  type: "any_speaking_node",
  label: "念一句",
  description: "",
  category: "",
  config: {
    text: { type: "template", required: true, label: "文本" },
    engine: { type: "string", default: "clone", options_from: "speech_engines", label: "引擎" },
    voice: { type: "string", required: true, depends_on: "engine", options_from: "speech_voices", label: "音色" },
  },
  outputs: ["asset_id"],
  output_types: {},
  output_labels: {},
} as unknown as WorkflowNodeType;

function renderInspector(config: Record<string, unknown>) {
  const asked: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/workflows/field-options")) {
      asked.push(`${url.searchParams.get("source")}:${url.searchParams.get("parent")}`);
      const parent = url.searchParams.get("parent");
      body =
        url.searchParams.get("source") === "speech_engines"
          ? [{ value: "clone", label: "克隆音色" }, { value: "edge", label: "Edge" }]
          : parent === "edge"
            ? [{ value: "zh-CN-Xiaoxiao", label: "晓晓" }]
            : [{ value: "v1", label: "我的音色" }];
    }
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const onChange = vi.fn();
  const node = { id: "n1", type: "any_speaking_node", position: { x: 0, y: 0 }, config };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
      <ReactFlowProvider>
      <NodeInspector
        node={node as never}
        meta={META}
        graph={{ nodes: [node], edges: [] } as never}
        registry={new Map([["any_speaking_node", META]])}
        workspaceId="w1"
        onChange={onChange}
        onApplyGraph={vi.fn()}
      />
      </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { asked, onChange };
}

const fieldLabels = () =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-field-key]")).map((el) => el.dataset.fieldKey);

describe("声明了选项来源的字段", () => {
  it("按声明顺序排,音色只有一格", async () => {
    renderInspector({ text: "你好", engine: "edge", voice: "" });
    await waitFor(() => expect(fieldLabels()).toEqual(["text", "engine", "voice"]));
  });

  it("清单从通用接口取,依赖字段的值作为 parent 带上(没填时用声明的默认值)", async () => {
    const { asked } = renderInspector({ text: "你好" });
    await waitFor(() => expect(asked).toEqual(expect.arrayContaining(["speech_engines:", "speech_voices:clone"])));
  });

  it("引擎换了,音色清单跟着换,旧的音色被清掉", async () => {
    const user = userEvent.setup();
    const { asked, onChange } = renderInspector({ text: "你好", engine: "clone", voice: "v1" });
    await waitFor(() => expect(asked).toContain("speech_voices:clone"));
    const engineField = document.querySelector<HTMLElement>('[data-field-key="engine"]')!;
    await user.click(within(engineField).getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Edge" }));
    expect(onChange).toHaveBeenCalledWith({ config: { text: "你好", engine: "edge", voice: "" } });
  });
});
