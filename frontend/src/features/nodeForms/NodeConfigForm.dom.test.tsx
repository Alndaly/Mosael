/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 节点表单离开工作流也能用:没有图、没有数据边,只给声明和配置。
 *
 * 创意画板上「跑一个工具」的格子就是这种宿主 —— 它要的是同一张表单(同样的下拉来源、同样的
 * 基础 / 高级分档、同样按素材类型给素材),而不是再抄一份。这里用的节点类型名是假的,钉住
 * 「表单不认识具体节点」。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  NodeConfigForm,
  nodeConfigTiers,
  useNodeFieldOptions,
  type ConfigSpec,
} from "@/features/nodeForms/NodeConfigForm";

beforeAll(() => {
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

//: 形状和 /api/workflows/node-types 发下来的一样(label、data_type 由后端贴好)。
const SPECS = {
  video: { type: "template", required: true, label: "视频", data_type: "asset" },
  platform: { type: "string", options_from: "some_source", label: "平台" },
  page: { type: "number", advanced: true, label: "页码" },
  expert: { type: "string", active_when: { platform: "x" }, label: "只对 x 有用" },
} as unknown as Record<string, ConfigSpec>;

function Host({ config }: { config: Record<string, unknown> }) {
  const fieldOptions = useNodeFieldOptions({ specs: SPECS, config, workspaceId: "w1", nodeType: "plugin.any.tool" });
  const { basic } = nodeConfigTiers(SPECS, config);
  return (
    <NodeConfigForm
      fields={basic}
      config={config}
      workspaceId="w1"
      variables={[]}
      fieldOptions={fieldOptions}
      onSetConfig={vi.fn()}
      onTypeConfig={vi.fn()}
    />
  );
}

function renderForm(config: Record<string, unknown>) {
  const asked: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/workflows/field-options")) {
      asked.push(`${url.searchParams.get("source")}:${url.searchParams.get("node_type")}`);
      body = [{ value: "x", label: "X 平台" }];
    } else if (url.pathname.endsWith("/assets")) {
      asked.push("assets");
      body = [{ id: "a1", name: "开场.mp4", original_filename: "open.mp4" }];
    }
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Host config={config} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { asked };
}

const fieldKeys = () =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-field-key]")).map((el) => el.dataset.fieldKey);

describe("节点表单", () => {
  it("高级项和此刻不参与的字段都不在基础档里", () => {
    expect(nodeConfigTiers(SPECS, {}).basic.map(([key]) => key)).toEqual(["video", "platform"]);
    expect(nodeConfigTiers(SPECS, {}).advanced.map(([key]) => key)).toEqual(["page"]);
    expect(nodeConfigTiers(SPECS, { platform: "x" }).basic.map(([key]) => key)).toEqual(["video", "platform", "expert"]);
    expect(nodeConfigTiers(SPECS, {}, (key) => key === "video").basic.map(([key]) => key)).toEqual(["platform"]);
  });

  it("没有宿主的连线时,字段只有手填 / 下拉,不给「接上游」的开关", async () => {
    renderForm({});
    await waitFor(() => expect(fieldKeys()).toEqual(["video", "platform"]));
    expect(document.body.textContent).not.toContain("wfInputManual");
  });

  it("下拉按声明去问后端,素材型字段给工作区素材", async () => {
    const { asked } = renderForm({ video: "a1" });
    await waitFor(() => expect(asked).toEqual(expect.arrayContaining(["some_source:plugin.any.tool", "assets"])));
    const video = document.querySelector<HTMLElement>('[data-field-key="video"]')!;
    await waitFor(() => expect(within(video).getByRole("combobox").textContent).toContain("开场.mp4"));
  });
});
