/** @vitest-environment jsdom */
/**
 * **「引用即发送」在检查器里看得见**:大模型节点的提示词里 `{{…}}` 引用了图片素材时,「要模型看的图片」
 * 那一格下面自动列出**那几处引用**(维护者:「对这种通过 `@` 引用了图片素材的 LLM 节点,其中的
 * 『要模型看的图片』应该自动同步」)。钉住:
 *
 * - 提示词里引用了图片素材 → 那一块出现,写着引用的**来源**(「素材 · 素材」这种「节点 · 输出」);
 * - 手动挑的缩略图和自动来的分开:自动那一块不是缩略图([data-asset-tile] 一张都没多);
 * - 去掉一处 → 写进 `<字段>_excluded`(运行时的取图认它,见后端 binding.with_referenced_assets);
 * - 引用的是**不可能装素材**的输出(素材节点的名字)→ 那一块不出现:它本来就只是文字。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactFlowProvider } from "@xyflow/react";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
//: 静态知道是哪张素材时(源节点是「素材」且写死了 id)要查它的种类:这里给一份小的,别真发请求。
//: 别的一并照原样(表单那一层还要 useAllAssetCards 之类的)。
vi.mock("@/lib/assetQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/assetQueries")>()),
  useAssetDetails: (ids: readonly string[]) => ({
    byId: new Map(ids.filter((id) => id === "img-a").map((id) => [id, { id, kind: "image", name: "猫" }])),
    settled: true,
  }),
  useAssetSearch: () => ({
    text: "", search: vi.fn(), items: [], isLoading: false, isError: false, error: null,
    hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn(), refetch: vi.fn(),
  }),
  useAllAssetCards: () => [],
}));

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
    system: { type: "template" },
    //: 声明和 NODE_TYPES 里那一份一致(type / media / editor / ref_assets_from / edited_by)。
    image_asset_ids: { type: "template", media: ["image"], editor: "asset_grid", ref_assets_from: ["prompt", "system"] },
    image_asset_ids_excluded: { type: "list", edited_by: "image_asset_ids" },
  },
  outputs: ["text", "json", "response_format_used"],
  output_types: {},
  output_labels: {},
  plugin_name: "",
  tool_name: "",
};

const PIC: WorkflowNodeType = {
  type: "asset",
  label: "素材",
  description: "",
  category: "",
  config: { asset_id: { type: "template", required: true } },
  outputs: ["asset_id", "name"],
  //: 名字是**文字**输出 —— 引用它不会被当成「要模型看的图」(后端那一道线同一条)。
  output_types: { asset_id: "asset", name: "text" },
  output_labels: { asset_id: "素材", name: "名字" },
  plugin_name: "",
  tool_name: "",
};

function renderLlm(prompt: string, config: Record<string, unknown> = {}) {
  const pic = { id: "pic", type: "asset", name: "素材", config: { asset_id: "img-a" } };
  const node = { id: "ask", type: "llm", config: { prompt, ...config } };
  const graph: WorkflowGraph = { nodes: [pic, node] as never, edges: [] };
  const onChange = vi.fn();
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={LLM}
            graph={graph}
            registry={new Map([["llm", LLM], ["asset", PIC]])}
            workspaceId="w1"
            onChange={onChange}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { onChange, ...view };
}

const autoBlock = () => document.querySelector("[data-auto-images]");

describe("检查器里自动同步的那几处引用", () => {
  it("提示词里引用了图片素材:那一块出现,写着引用的来源(「素材 · 素材」),和手动挑的分开", () => {
    renderLlm("这张图里是什么?{{pic.asset_id}}");
    const block = autoBlock();
    expect(block).not.toBeNull();
    const one = block!.querySelector("[data-auto-image-ref='pic.asset_id']");
    expect(one).not.toBeNull();
    //: 名字按引用目录那一套:节点名 · 输出的显示名(不是 `pic.asset_id` 这种路径写法)。
    expect(one!.textContent).toContain("素材");
    expect(one!.getAttribute("data-auto-image-on")).toBe("true");
    //: 自动来的不是手动格子:缩略图那一侧一张都没多。
    expect(document.querySelectorAll("[data-asset-tile]")).toHaveLength(0);
  });

  it("去掉一处:把引用路径写进那一格的排除清单", () => {
    const { onChange } = renderLlm("看图 {{pic.asset_id}}");
    fireEvent.click(document.querySelector("[data-auto-image-ref='pic.asset_id'] [data-auto-image-toggle]")!);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ image_asset_ids_excluded: ["pic.asset_id"] }) }),
      undefined,
    );
  });

  it("已经排除过的那一处还看得见(点回来即可恢复)", () => {
    renderLlm("看图 {{pic.asset_id}}", { image_asset_ids_excluded: ["pic.asset_id"] });
    const one = document.querySelector("[data-auto-image-ref='pic.asset_id']")!;
    expect(one.getAttribute("data-auto-image-on")).toBe("false");
  });

  it("系统提示词里引用的也算(和运行时同一条:prompt → system)", () => {
    renderLlm("图里是什么?", { system: "看着 {{pic.asset_id}} 回答" });
    expect(document.querySelector("[data-auto-image-ref='pic.asset_id']")).not.toBeNull();
  });

  it("引用的是不可能装素材的输出(素材的名字):那一块不出现,它本来就只是文字", () => {
    renderLlm("这份素材叫 {{pic.name}}");
    expect(autoBlock()).toBeNull();
  });

  it("提示词里没有引用:那一块不出现", () => {
    renderLlm("随便写点什么");
    expect(autoBlock()).toBeNull();
  });

  it("手动挑的照旧在格子里(自动那一块不挤掉它们)", () => {
    renderLlm("看图 {{pic.asset_id}}", { image_asset_ids: "img-a" });
    expect(document.querySelectorAll("[data-asset-tile]")).toHaveLength(1);
    expect(autoBlock()).not.toBeNull();
  });
});

//: 引用目录那一套的名字(「节点 · 输出」)在别处也钉着(workflowRefCatalog);这里只用得到它给的那一行字。
void screen;
