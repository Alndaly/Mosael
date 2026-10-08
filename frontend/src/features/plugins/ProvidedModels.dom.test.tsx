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
    ({
      pluginModelTakes: "pluginModelTakes {roles}",
      pluginModelRequired: "{role} pluginModelRequired",
      pluginGenerationError: "pluginGenerationError {error}",
      pluginGenerationStale: "没刷出来:{error} · 列着的是 {time}的清单",
      pluginModelsTitle: "{name} 提供的{Noun}",
      pluginModelsSearch: "搜 {n} 个{noun}",
      pluginModelsStale: "这是 {time}的清单,现在刷不出来:{error}",
      entryFromGroup: "来自 {name}",
      entryFullWorkflow: "完整工作流",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance, PluginProvidedModel } from "@/api/client";
import { GenerationModelsRow } from "./ProvidedModels";
import { hoverHint } from "@/test/hint";

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
        noun="工作流"
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
    // 显示名「模型」,悬停给参数键(像用户那样把指针停上去读说明)。
    const param = within(portrait).getByText("模型");
    expect(await hoverHint(param)).toBe("4.ckpt_name");
    fireEvent.pointerLeave(param, { pointerType: "mouse" });

    fireEvent.click(screen.getByRole("button", { name: /pluginRefreshModels/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("模型多了给搜索框", async () => {
    listPluginInstanceModels.mockResolvedValue(
      Array.from({ length: 8 }, (_, index) => model({ id: `w${index}.json`, label: `工作流 ${index}` })),
    );
    wrap(<GenerationModelsRow instance={instance} noun="工作流" status={{ models: 8, error: "" }} refreshing={false} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "pluginModelsView" }));
    const search = await screen.findByPlaceholderText("搜 8 个工作流");
    //: 交出来的是什么由插件说(ComfyUI:工作流),标题、搜索框跟着它,不写死「模型」
    expect(screen.getByRole("dialog").textContent).toContain("ComfyUI · 本机 提供的工作流");
    fireEvent.change(search, { target: { value: "工作流 3" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("没刷出来:说原因,还没有模型就不让点「查看」", () => {
    wrap(
      <GenerationModelsRow instance={instance} noun="工作流" status={{ models: null, error: "连不上" }} refreshing={false} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText("pluginGenerationError 连不上").className).toContain("text-destructive");
    // 原因可能很长(连不上的原话):这一格有上限,不把左边的标签和说明挤成一列窄条,放不下的悬停看全文
    expect(screen.getByText("pluginGenerationError 连不上").className).toMatch(/max-w-/);
    expect((screen.getByRole("button", { name: "pluginModelsView" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("现在刷不出来、手里是上一次的清单:行内和弹窗顶上都说清是哪一次的、现在连不上;给「重新连接」;不再写一句像刚刷过的时间", async () => {
    // 维护者:那一行写着「没刷出来:连不上」,弹窗却照常列出 28 个、底部写「1小时前刷新」
    listPluginInstanceModels.mockResolvedValue([model({})]);
    const onRefresh = vi.fn();
    wrap(<GenerationModelsRow instance={instance} noun="工作流" refreshing={false} onRefresh={onRefresh}
           status={{ models: 1, refreshed_at: "2026-09-25T10:00:00+00:00", error: "连不上这台 ComfyUI\nErrno 61" }} />);
    expect(document.body.textContent).toMatch(/没刷出来:连不上这台 ComfyUI · 列着的是 .+的清单/);
    fireEvent.click(screen.getByRole("button", { name: "pluginModelsView" }));
    await screen.findAllByRole("listitem");
    const banner = document.querySelector<HTMLElement>("[data-catalog-stale]")!;
    expect(banner.textContent).toMatch(/^这是 .+的清单,现在刷不出来:连不上这台 ComfyUI/);
    expect(document.querySelector("[data-stale]"), "清单压暗:是上一次的样子").not.toBeNull();
    expect(screen.queryByText(/pluginModelsRefreshed/), "底部不再写「x 前刷新」").toBeNull();
    fireEvent.click(within(banner).getByRole("button", { name: "pluginModelsReconnect" }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("清单好好的:顶上没有那句;表单入口和别的项左边对齐,第二行写来自哪张", async () => {
    const group = { id: "krea2.json", label: "krea2" };
    listPluginInstanceModels.mockResolvedValue([
      model({ id: "krea2.json", label: "krea2", group: { ...group, entry: "full", order: 0 } }),
      model({ id: "krea2.json#app", label: "快速出图", group: { ...group, entry: "form", order: 1 } }),
    ]);
    wrap(<GenerationModelsRow instance={instance} noun="工作流" refreshing={false} onRefresh={vi.fn()}
           status={{ models: 2, refreshed_at: "2026-09-25T10:00:00+00:00", error: "" }} />);
    fireEvent.click(screen.getByRole("button", { name: "pluginModelsView" }));
    const items = await screen.findAllByRole("listitem");
    expect(document.querySelector("[data-catalog-stale]")).toBeNull();
    const form = items.find((item) => item.getAttribute("data-entry") === "form")!;
    expect(form.className, "不往右缩一截").not.toMatch(/\bml-\d/);
    expect(form.textContent).toContain("来自 krea2");
  });

  it("原因的原文(errno、地址)不摆在这一格里,只说第一句人话", () => {
    wrap(
      <GenerationModelsRow instance={instance} noun="工作流" status={{ models: null, error: "连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8188:[Errno 61] Connection refused" }} refreshing={false} onRefresh={vi.fn()} />,
    );
    expect(screen.getByText("pluginGenerationError 连不上这台 ComfyUI,确认它在运行、地址填对")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Errno");
  });
});
