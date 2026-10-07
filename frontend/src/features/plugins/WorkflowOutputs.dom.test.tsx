/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 工作流库详情里「最近的产出」(维护者:「工作流产出这里应该是个图片集 然后要支持nsfw过滤」)。
 *
 * - 是一组:一批出的每一张都在、新的在前;先摆 8 张,「显示全部」展开;
 * - NSFW 和模型库同一套设置(modelPreviewSettings):判成 NSFW 的按「NSFW 预览」那一档模糊或不显示;不显示的点「显示这一张」
 *   只看这一张;灯箱里翻的是看得见的那几张;判错了经菜单标成是 / 不是 / 改回自动判断。
 */

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
const api = vi.hoisted(() => ({
  getWorkflowOutputs: vi.fn(),
  markWorkflowOutputNsfw: vi.fn(),
  getLocalNsfw: vi.fn(async () => ({ status: "missing", size_bytes: 0, pending: 0, scored: 0, message: "" })),
  installLocalNsfw: vi.fn(),
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
  assetPreviewUrl: (id: string) => `preview://${id}`,
  assetFileUrl: (id: string) => `file://${id}`,
  getAsset: vi.fn(async (id: string) => ({ id, kind: id.startsWith("v") ? "video" : "image", name: `产出 ${id}` })),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => false }));

import { setModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { WorkflowOutputs } from "./WorkflowOutputs";

const clean = { flagged: false, manual: null, reasons: [] };
const flagged = { flagged: true, manual: true, reasons: [] };
const output = (id: string, nsfw: typeof clean | typeof flagged = clean, kind = "image") =>
  ({ asset_id: id, kind, created_at: "2026-10-05T10:00:00", nsfw });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkflowOutputs instanceId="i1" workspaceId="w1" path="krea2-text-2-image.json" label="快速用krea2生图" />
    </QueryClientProvider>,
  );
}

const tile = (id: string) => document.querySelector<HTMLElement>(`[data-workflow-output="${id}"]`)!;

beforeEach(() => {
  window.localStorage.clear();
  setModelPreviewSettings({ level: "clear", nsfw: "blur" });
});
afterEach(() => {
  openImagePreview.mockReset();
  vi.clearAllMocks();
});

describe("最近的产出", () => {
  it("一组:新的在前,先摆 8 张,「显示全部」展开到全部", async () => {
    api.getWorkflowOutputs.mockResolvedValue({ outputs: Array.from({ length: 10 }, (_, index) => output(`a${index}`)), more: false });
    mount();
    const section = await screen.findByRole("region", { name: "workflowLastOutput" });
    expect(section.querySelectorAll("[data-workflow-output]")).toHaveLength(8);
    fireEvent.click(within(section).getByRole("button", { name: "modelTagsAll" }));
    expect(section.querySelectorAll("[data-workflow-output]")).toHaveLength(10);
    expect(api.getWorkflowOutputs).toHaveBeenCalledWith("i1", "w1", "krea2-text-2-image.json");
  });

  it("NSFW「模糊」:判成 NSFW 的那张糊着(悬停看清),别的清晰;角上一枚 NSFW", async () => {
    api.getWorkflowOutputs.mockResolvedValue({ outputs: [output("a1"), output("a2", flagged)], more: false });
    mount();
    await screen.findByRole("region", { name: "workflowLastOutput" });
    expect(tile("a1").dataset.treatment).toBe("clear");
    expect(tile("a2").dataset.treatment).toBe("heavy");
    expect(tile("a2").querySelector("img")?.className).toContain("blur-xl");
    expect(tile("a2").querySelector("img")?.className).toContain("group-hover/thumb:blur-none");
    expect(tile("a1").querySelector("img")?.className).not.toContain("blur");
    expect(tile("a2").querySelector("[data-nsfw-mark]")).toBeTruthy();
    expect(tile("a1").querySelector("[data-nsfw-mark]")).toBeNull();
  });

  it("NSFW「不显示」:不去取那张图,只剩「已隐藏」;点「显示这一张」只看这一张;灯箱里翻的不带藏着的", async () => {
    act(() => setModelPreviewSettings({ level: "clear", nsfw: "hidden" }));
    api.getWorkflowOutputs.mockResolvedValue({
      outputs: [output("a1"), output("a2", flagged), output("a3"), output("a4", flagged)], more: false,
    });
    mount();
    await screen.findByRole("region", { name: "workflowLastOutput" });
    expect(tile("a2").querySelector("img"), "藏着的不取图").toBeNull();
    expect(tile("a2").querySelector("[data-hidden-preview]")?.textContent).toContain("modelPreviewHidden");
    await waitFor(() => expect(within(tile("a1")).getByRole("button", { name: "viewFullSizeOf" })).toBeTruthy());
    await waitFor(() => {
      fireEvent.click(within(tile("a1")).getByRole("button", { name: "viewFullSizeOf" }));
      expect(openImagePreview).toHaveBeenLastCalledWith({
        src: "preview://a1", title: "产出 a1",
        gallery: [{ src: "preview://a1", title: "产出 a1" }, { src: "preview://a3", title: "产出 a3" }],
      });
    });
    fireEvent.click(within(tile("a2")).getByRole("button", { name: /modelShowHiddenPreview/ }));
    expect(tile("a2").dataset.treatment).toBe("clear");
    expect(tile("a2").querySelector("img")?.getAttribute("src")).toBe("thumb://a2");
    expect(tile("a4").dataset.treatment, "只看这一张:另一张判成 NSFW 的照旧藏着").toBe("hidden");
  });

  it("判错了经菜单标成 NSFW;改完照新的判断画", async () => {
    api.getWorkflowOutputs.mockResolvedValue({ outputs: [output("a1")], more: false });
    api.markWorkflowOutputNsfw.mockResolvedValue(flagged);
    mount();
    await screen.findByRole("region", { name: "workflowLastOutput" });
    fireEvent.pointerDown(within(tile("a1")).getByRole("button", { name: "workflowOutputActions" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "modelNsfwMark" }));
    await waitFor(() => expect(api.markWorkflowOutputNsfw).toHaveBeenCalledWith("i1", { workspace_id: "w1", asset_id: "a1", nsfw: true }));
    await waitFor(() => expect(tile("a1").dataset.treatment).toBe("heavy"));
  });

  it("视频是第一帧加一枚播放;音频一行一条播放条", async () => {
    api.getWorkflowOutputs.mockResolvedValue({ outputs: [output("v1", clean, "video"), output("s1", clean, "audio")], more: false });
    mount();
    await screen.findByRole("region", { name: "workflowLastOutput" });
    expect(tile("v1").querySelector("img")?.getAttribute("src")).toBe("thumb://v1");
    expect(tile("v1").querySelector("svg.lucide-play")).toBeTruthy();
    expect(tile("s1").tagName).toBe("LI");
    expect(tile("s1").querySelector("img")).toBeNull();
  });
});
