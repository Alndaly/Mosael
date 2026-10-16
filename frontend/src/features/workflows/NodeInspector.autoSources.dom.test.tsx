/** @vitest-environment jsdom */
/**
 * **生成节点的「输入素材」走的是共用的格子控件**(`editor: "asset_grid"`),不是一个自绘的控件。
 *
 * 这一格的值是一行一条 `素材id:角色`(声明 `lines` + `entry_labels: "source_roles"`),所以这里钉住:
 *
 * - 画出来的是那个格子(`[data-asset-grid]`,mode = lines),不是按角色两条下拉成行的自绘控件;
 * - 每份素材带**角色角标**,挑一份写回的是**行的列表** `id:角色`;
 * - **「引用即发送」**在格子里看得见:提示词里 `{{…}}` 引用到的素材单独一行,写着引用的来源;
 * - 默认角色是声明里的「参考图」,改得动(记在 `source_assets_roles`,一条一个 `引用路径:角色`);
 * - × 去掉一处 → 写进 `source_assets_excluded`(运行时的取图认它);已排除过的还看得见,点回来即可恢复;
 * - **模型不收这个角色时明说**「不会被送进去」—— 沉默地丢掉和硬塞都不许;
 * - 静态就知道是哪一份素材、而它不是这个角色要的那一类(引用到一段视频):当场标出来。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/app/preferences", () => ({
  //: 插值那两句**按真的模板**给:只回 key 的话 `.replace("{role}", …)` 什么也换不着,
  //: 这一格要看的正是「说的是哪个角色」。
  useI18n: () => (key: string) => (key === "wfGenAutoSourcesRejected"
    ? "这个模型不接受{role},引用的图不会被送进去"
    : key === "wfGenAutoSourcesWrongKind" ? "不是{kind},不会发送" : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));
//: 静态知道是哪份素材时(源节点是「素材」且写死了 id)要查它的种类:这里给一份小的,别真发请求。
vi.mock("@/lib/assetQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/assetQueries")>()),
  useAssetDetails: (ids: readonly string[]) => ({
    byId: new Map(
      ids
        .filter((id) => id === "img-a" || id === "clip-v")
        .map((id) => [id, { id, kind: id === "clip-v" ? "video" : "image", name: id === "clip-v" ? "一段视频" : "猫" }]),
    ),
    settled: true,
  }),
  useAssetSearch: () => ({
    text: "", search: vi.fn(), items: [], isLoading: false, isError: false, error: null,
    hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn(), refetch: vi.fn(),
  }),
  useAllAssetCards: () => ({ items: [], isSuccess: true, hasNextPage: false, isFetchingNextPage: false, isError: false, fetchNextPage: vi.fn() }),
}));

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

afterEach(cleanup);

const GEN: WorkflowNodeType = {
  type: "ai_generate",
  label: "AI 生成素材",
  description: "",
  category: "",
  config: {
    provider_profile_id: { type: "string" },
    provider: { type: "string", required: true },
    model: { type: "string", required: true },
    kind: { type: "string", required: true, options: ["image", "video", "audio"] },
    prompt: { type: "template" },
    parameters: { type: "object" },
    //: 声明和 NODE_TYPES 里那一份一致(type / lines / entry_labels / editor / ref_assets_* / edited_by)。
    source_assets: {
      type: "template", lines: true, entry_labels: "source_roles", editor: "asset_grid",
      ref_assets_from: ["prompt"], ref_assets_role: "reference_image", ref_assets_gate: "generation_source_role",
    },
    source_assets_excluded: { type: "list", edited_by: "source_assets" },
    source_assets_roles: { type: "list", edited_by: "source_assets" },
  },
  outputs: ["asset_id", "asset_ids", "generation_id"],
  output_types: { asset_id: "asset", asset_ids: "json", generation_id: "text" },
  output_labels: { asset_id: "素材", asset_ids: "全部产出", generation_id: "生成任务" },
  plugin_name: "",
  tool_name: "",
};

const ASSET: WorkflowNodeType = {
  type: "asset",
  label: "素材",
  description: "",
  category: "",
  config: { asset_id: { type: "template", required: true } },
  outputs: ["asset_id", "name"],
  //: 名字是**文字**输出 —— 引用它不会被当成「要发的素材」(后端那一道线同一条)。
  output_types: { asset_id: "asset", name: "text" },
  output_labels: { asset_id: "素材", name: "名字" },
  plugin_name: "",
  tool_name: "",
};

/** 选中的模型收哪几种角色 —— 判据和运行时同一份(描述符的 parameter_keys)。 */
const PROFILE = {
  id: "p1", vendor: "bytedance", enabled: true, auth_type: "api_key", oauth_linked: false,
  base_url: "https://ark.example/api/v3", capability_ids: ["image"],
};

function renderGen({
  parameterKeys,
  config = {},
  assets = { pic: "img-a" },
}: {
  parameterKeys: string[];
  config?: Record<string, unknown>;
  assets?: Record<string, string>;
}) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/settings/providers")) body = [PROFILE];
    if (url.pathname.endsWith("/generation/options") && url.searchParams.get("kind") === "image") {
      body = [{
        id: "p1:image:doubao-seedream-4-0-250828", provider_profile_id: "p1", profile_name: "火山", label: "火山 · Seedream",
        provider: "bytedance", model: "doubao-seedream-4-0-250828", kind: "image", model_label: "Seedream",
        capabilities: { modes: ["image-to-image"], parameter_keys: parameterKeys, prompt: "optional" },
        capabilities_known: true, adapter_available: true, is_default: true,
      }];
    }
    if (url.pathname === "/api/assets") body = { items: [], next_cursor: null, total: 0 };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const sources = Object.entries(assets).map(([id, asset_id]) => ({ id, type: "asset", name: id, config: { asset_id } }));
  const node = {
    id: "draw", type: "ai_generate", position: { x: 0, y: 0 },
    config: {
      provider_profile_id: "p1", provider: "bytedance", model: "doubao-seedream-4-0-250828", kind: "image",
      prompt: "照这张画一张 {{pic.asset_id}}", ...config,
    },
  };
  const onChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <ReactFlowProvider>
          <NodeInspector
            node={node as never}
            meta={GEN}
            graph={{ nodes: [...sources, node], edges: [] } as unknown as WorkflowGraph}
            registry={new Map([["ai_generate", GEN], ["asset", ASSET]])}
            workspaceId="w1"
            onChange={onChange}
            onApplyGraph={vi.fn()}
          />
        </ReactFlowProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { onChange };
}

const grid = () => document.querySelector("[data-asset-grid]");
const autoBlock = () => document.querySelector("[data-auto-images]");
const autoChip = (path = "pic.asset_id") => document.querySelector(`[data-auto-image-ref='${path}']`);
const roleOf = (path = "pic.asset_id") => autoChip(path)?.getAttribute("data-auto-image-role");

/** 换一处自动引用的角色(点开角标、选一项)—— 和用户在界面上点两下是同一条路。 */
async function pickRole(path: string, label: string) {
  fireEvent.click(autoChip(path)!.querySelector("[data-role-badge]")!);
  await userEvent.click(await screen.findByRole("menuitemradio", { name: label }));
}

describe("生成节点的「输入素材」:共用的格子控件", () => {
  it("画出来的是那个格子(一行一条 `素材id:角色`),不是按角色两条下拉的自绘控件", () => {
    renderGen({ parameterKeys: ["reference_image"] });
    const field = grid()!;
    expect(field).not.toBeNull();
    expect(field.getAttribute("data-asset-grid-mode")).toBe("lines");
    //: 这一格的声明认角色,所以有角色角标;手改的是同一份值(不是另一套控件写出来的)。
    expect(field.querySelector("[data-auto-image-ref='pic.asset_id']")).not.toBeNull();
  });

  it("提示词里引用到的素材单独一行摆出来,名字是引用的来源,默认角色是「参考图」", () => {
    renderGen({ parameterKeys: ["reference_image"] });
    expect(autoChip()).not.toBeNull();
    expect(autoChip()!.textContent).toContain("素材");
    expect(autoChip()!.getAttribute("data-auto-image-on")).toBe("true");
    //: 默认角色是声明里的那个(「参考图」),展示在角标上。
    expect(roleOf()).toBe("reference_image");
    expect(autoChip()!.querySelector("[data-role-badge]")!.textContent).toBe("genReferenceImage");
  });

  it("改角色:记在 source_assets_roles 里(一条一个 `引用路径:角色`)", async () => {
    const { onChange } = renderGen({ parameterKeys: ["reference_image", "first_frame"] });
    await pickRole("pic.asset_id", "genFirstFrame");
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ source_assets_roles: ["pic.asset_id:first_frame"] }),
      }),
      undefined,
    );
  });

  it("改回声明里的默认角色:那一格记账里就不留它了(没记的就是默认)", async () => {
    const { onChange } = renderGen({
      parameterKeys: ["reference_image", "first_frame"],
      config: { source_assets_roles: ["pic.asset_id:first_frame"] },
    });
    await pickRole("pic.asset_id", "genReferenceImage");
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ source_assets_roles: [] }) }),
      undefined,
    );
  });

  it("× 去掉一处:把引用路径写进那一格的排除清单", () => {
    const { onChange } = renderGen({ parameterKeys: ["reference_image"] });
    fireEvent.click(autoChip()!.querySelector("[data-auto-image-toggle]")!);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ source_assets_excluded: ["pic.asset_id"] }),
      }),
      undefined,
    );
  });

  it("已经排除过的那一处还看得见,点回来即可恢复", () => {
    renderGen({ parameterKeys: ["reference_image"], config: { source_assets_excluded: ["pic.asset_id"] } });
    expect(autoChip()!.getAttribute("data-auto-image-on")).toBe("false");
  });

  it("模型不收参考图:明说不会被送进去,不是沉默", async () => {
    renderGen({ parameterKeys: ["first_frame"] });
    const rejected = await waitFor(() => {
      const found = autoChip()!.querySelector("[data-auto-image-rejected]");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(rejected.textContent).toContain("genReferenceImage");
    expect(rejected.textContent).toContain("不会被送进去");
  });

  it("模型什么角色都不收(认不出的模型):也说清", async () => {
    renderGen({ parameterKeys: [] });
    const rejected = await waitFor(() => {
      const found = autoChip()!.querySelector("[data-auto-image-rejected]");
      expect(found).not.toBeNull();
      return found!;
    });
    //: 一个角色都不收:角标照在(声明里有角色),但点开的菜单里每一项都标着「这个模型不收」。
    expect(rejected.textContent).toContain("不会被送进去");
  });

  it("引用到的是一段视频:当场标出它不是这个角色要的那类素材", () => {
    renderGen({
      parameterKeys: ["reference_image"],
      assets: { clip: "clip-v" },
      config: { prompt: "看看这段 {{clip.asset_id}}" },
    });
    const wrong = autoChip("clip.asset_id")!.querySelector("[data-auto-image-skipped]")!;
    expect(wrong).not.toBeNull();
    expect(wrong.textContent).toContain("kindVideo");
    expect(wrong.textContent).toContain("不会发送");
  });

  it("提示词里没有引用:那一块不出现", async () => {
    renderGen({ parameterKeys: ["reference_image"], config: { prompt: "随便画一张" } });
    await screen.findByText("wfGenModel");
    expect(grid()).not.toBeNull();
    expect(autoBlock()).toBeNull();
  });
});
