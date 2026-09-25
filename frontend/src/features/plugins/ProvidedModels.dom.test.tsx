/** @vitest-environment jsdom */

/**
 * 替宿主做生成的插件在插件页上:不只是「2 个模型」,而是**哪两个、各收什么、能调什么**。
 * 不认识任何一家插件 —— 数据是 `/plugins/instances/{id}/models` 给的,这里只看怎么摆。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listPluginInstanceModels } = vi.hoisted(() => ({ listPluginInstanceModels: vi.fn() }));
vi.mock("@/api/client", () => ({ listPluginInstanceModels }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({ pluginModelTakes: "pluginModelTakes {roles}", pluginModelRequired: "{role} pluginModelRequired" })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance, PluginProvidedModel } from "@/api/client";
import { GenerationModelsRow } from "./ProvidedModels";

const instance = { id: "i1", name: "ComfyUI · 本机" } as PluginInstance;

function model(overrides: Partial<PluginProvidedModel>): PluginProvidedModel {
  return {
    id: "portrait.json",
    label: "portrait",
    kind: "image",
    enabled: true,
    modes: ["text-to-image", "image-to-image"],
    inputs: [{ role: "reference_image", max: 1, required: false }],
    host_parameters: ["size", "seed", "num_images"],
    parameters: [
      { key: "4.ckpt_name", title: "模型", type: "string", advanced: false },
      { key: "3.steps", title: "步数", type: "integer", advanced: false },
      { key: "3.denoise", title: "降噪强度", type: "number", advanced: true },
    ],
    ...overrides,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

beforeEach(() => {
  listPluginInstanceModels.mockReset();
});

describe("插件提供的模型", () => {
  it("卡片上是摘要;点开是清单:名字、种类、模式、收什么、几个参数,展开看是哪几个", async () => {
    listPluginInstanceModels.mockResolvedValue([
      model({}),
      model({
        id: "upscale.json", label: "upscale", modes: ["image-to-image"], parameters: [],
        inputs: [{ role: "reference_image", max: 1, required: true }], host_parameters: [],
      }),
      model({ id: "video/wan.json", label: "wan", kind: "video", modes: ["image-to-video"], enabled: false,
              inputs: [{ role: "first_frame", max: 1, required: false }] }),
    ]);
    const onRefresh = vi.fn();
    wrap(
      <GenerationModelsRow
        instance={instance}
        status={{ models: 3, refreshed_at: "2026-09-25T10:00:00+00:00", error: "" }}
        refreshing={false}
        onRefresh={onRefresh}
      />,
    );
    expect(screen.getByText("pluginGenerationCount")).toBeTruthy();
    expect(listPluginInstanceModels).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "pluginModelsView" }));

    const items = await screen.findAllByRole("listitem");
    expect(listPluginInstanceModels).toHaveBeenCalledWith("i1");
    const portrait = items.find((item) => item.textContent?.includes("portrait"))!;
    expect(portrait.textContent).toContain("pluginModelKind_image");
    expect(portrait.textContent).toContain("genModeTextToImage · genModeImageToImage");
    expect(portrait.textContent).toContain("pluginModelTakes genReferenceImage");
    expect(portrait.textContent).toContain("pluginModelParams");
    const upscale = items.find((item) => item.textContent?.includes("upscale"))!;
    expect(upscale.textContent).toContain("genReferenceImage pluginModelRequired");
    const wan = items.find((item) => item.textContent?.includes("wan"))!;
    expect(wan.textContent).toContain("pluginModelDisabled");

    // 参数名要展开才看得到 —— 清单第一眼只给每个模型一行
    expect(screen.queryByText("步数")).toBeNull();
    fireEvent.click(within(portrait).getByRole("button"));
    expect(within(portrait).getByText("步数")).toBeTruthy();
    expect(within(portrait).getByText("genParam_size · genParam_seed · genParam_num_images")).toBeTruthy();
    expect(within(portrait).getByText("pluginModelAdvancedParams")).toBeTruthy();
    expect(within(portrait).getByText("模型").getAttribute("title")).toBe("4.ckpt_name");

    fireEvent.click(screen.getByRole("button", { name: /pluginRefreshModels/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("模型多了给搜索框", async () => {
    listPluginInstanceModels.mockResolvedValue(
      Array.from({ length: 8 }, (_, index) => model({ id: `w${index}.json`, label: `工作流 ${index}` })),
    );
    wrap(<GenerationModelsRow instance={instance} status={{ models: 8, error: "" }} refreshing={false} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "pluginModelsView" }));
    const search = await screen.findByPlaceholderText("pluginModelsSearch");
    fireEvent.change(search, { target: { value: "工作流 3" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("没刷出来:说原因,还没有模型就不让点「查看」", () => {
    wrap(
      <GenerationModelsRow instance={instance} status={{ models: null, error: "连不上" }} refreshing={false} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText("pluginGenerationError").className).toContain("text-destructive");
    expect((screen.getByRole("button", { name: "pluginModelsView" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
