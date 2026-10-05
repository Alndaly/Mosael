/** @vitest-environment jsdom */

/**
 * 生成表单里选大模型 / LoRA 那一格(参数上写着 `x-model-folder`):下拉里每一项有缩略图(没图就是按目录分的占位)、
 * 底模和触发词;选中带触发词的那一项,能一键把触发词加进提示词。数据来自那个连接的模型库,不认识哪一家插件。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
  modelThumbnailUrl: (instance: string, folder: string, name: string) => `thumbnail://${instance}/${folder}/${name}`,
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ModelFilePicker } from "@/components/generation/ModelFilePicker";
import type { DeclaredParameter } from "@/lib/generationCapabilities";
import { withTriggerWords } from "@/lib/generationCapabilities";

const loras = Array.from({ length: 10 }, (_, index) => `style_${index}.safetensors`);

const parameter: DeclaredParameter = {
  key: "10.lora_name",
  type: "string",
  label: "LoRA",
  description: "",
  defaultValue: "style_0.safetensors",
  options: ["sub\\anima.safetensors", ...loras],
  optionLabels: {},
  multiline: false,
  advanced: false,
  modelFolder: "loras",
};

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
});

beforeEach(() => {
  window.localStorage.clear();
  api.getModelLibrary.mockReset();
  api.getModelLibrary.mockResolvedValue({
    folders: [{ name: "loras", count: 11 }],
    models: [
      { folder: "loras", name: "style_1.safetensors", family: "Illustrious", family_source: "metadata",
        triggers: ["1girl", "watercolor"], triggers_source: "metadata", has_preview: true, used_by: [], title: "" },
      { folder: "loras", name: "sub\\anima.safetensors", family: "anima", family_source: "metadata",
        triggers: [], triggers_source: "", has_preview: false, used_by: [], title: "" },
      // 别的目录里同名的不算
      { folder: "checkpoints", name: "style_2.safetensors", family: "SDXL", family_source: "metadata",
        triggers: ["nope"], triggers_source: "metadata", has_preview: true, used_by: [], title: "" },
    ],
    missing: [],
    download: { route: "none", note: "" },
    downloads: [],
  });
});

function openList(): HTMLElement {
  fireEvent.click(screen.getByRole("combobox"));
  return document.querySelector<HTMLElement>("[data-radix-popper-content-wrapper] [role='listbox']")!;
}

describe("选模型文件的那一格", () => {
  it("下拉里每一项有缩略图或按目录分的占位,写着底模和触发词;读的是那个连接的模型库", async () => {
    wrap(<ModelFilePicker instanceId="i1" parameter={parameter} value="" onChange={vi.fn()} />);
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalledWith("i1", "safest"));
    await waitFor(() => expect(screen.getByRole("combobox").querySelector("[data-placeholder]")).toBeTruthy());
    const list = openList();
    const rows = within(list).getAllByRole("option");
    const styled = rows.find((row) => row.textContent?.includes("style_1.safetensors"))!;
    expect(styled.querySelector("img")?.getAttribute("src")).toBe("thumbnail://i1/loras/style_1.safetensors");
    expect(styled.textContent).toContain("Illustrious");
    expect(styled.textContent).toContain("1girl, watercolor");
    const anima = rows.find((row) => row.textContent?.includes("anima.safetensors"))!;
    expect(anima.querySelector("[data-placeholder='loras']")).toBeTruthy();
    expect(anima.textContent).toContain("anima");
    const other = rows.find((row) => row.textContent?.includes("style_2.safetensors"))!;
    expect(other.textContent).not.toContain("nope");
  });

  it("选中带触发词的 LoRA:一键把触发词加进提示词", async () => {
    const onChange = vi.fn();
    const onUseTriggers = vi.fn();
    const { rerender } = wrap(
      <ModelFilePicker instanceId="i1" parameter={parameter} value="" onChange={onChange} onUseTriggers={onUseTriggers} />,
    );
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalled());
    const list = openList();
    fireEvent.click(within(list).getAllByRole("option").find((row) => row.textContent?.includes("style_1.safetensors"))!);
    expect(onChange).toHaveBeenCalledWith("style_1.safetensors");
    rerender(<ModelFilePicker instanceId="i1" parameter={parameter} value="style_1.safetensors" onChange={onChange}
                              onUseTriggers={onUseTriggers} />);
    const add = await screen.findByRole("button", { name: "modelTriggersAddToPrompt" });
    expect(screen.getByText("watercolor")).toBeTruthy();
    fireEvent.click(add);
    expect(onUseTriggers).toHaveBeenCalledWith(["1girl", "watercolor"]);
  });

  it("模型库读不到(连接停了):照旧是一个能选的下拉,只是没有缩略图和触发词", async () => {
    api.getModelLibrary.mockRejectedValue(new Error("用不了"));
    const onChange = vi.fn();
    wrap(<ModelFilePicker instanceId="i1" parameter={parameter} value="style_1.safetensors" onChange={onChange}
                          onUseTriggers={vi.fn()} />);
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalled());
    const list = openList();
    expect(within(list).getAllByRole("option").length).toBe(11);
    expect(screen.queryByRole("button", { name: "modelTriggersAddToPrompt" })).toBeNull();
  });
});

describe("预览图分档、NSFW 单独管(和模型库同一份设置)", () => {
  it("下拉里的缩略图照两组设置画:判成 NSFW 的按 NSFW 那一档(更严的),说明里写着 NSFW;不显示的不去取图", async () => {
    window.localStorage.setItem("mosael:model-previews", JSON.stringify({ level: "light", nsfw: "hidden" }));
    api.getModelLibrary.mockResolvedValue({
      folders: [{ name: "loras", count: 2 }], missing: [], download: { route: "none", note: "" }, downloads: [],
      models: [
        { folder: "loras", name: "style_1.safetensors", family: "", family_source: "", triggers: [], triggers_source: "",
          has_preview: true, used_by: [], title: "", nsfw: { flagged: false, manual: null, reasons: [] } },
        { folder: "loras", name: "style_2.safetensors", family: "", family_source: "", triggers: [], triggers_source: "",
          has_preview: true, used_by: [], title: "", nsfw: { flagged: true, manual: true, reasons: [] } },
      ],
    });
    wrap(<ModelFilePicker instanceId="i1" parameter={parameter} value="style_2.safetensors" onChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("combobox").querySelector("[data-hidden-preview]")).toBeTruthy());
    expect(screen.getByRole("combobox").querySelector("img")).toBeNull();
    const rows = within(openList()).getAllByRole("option");
    const row = (name: string) => rows.find((one) => one.textContent?.includes(name))!;
    expect(row("style_1.safetensors").querySelector("img")!.getAttribute("data-treatment")).toBe("light");
    expect(row("style_2.safetensors").querySelector("img")).toBeNull();
    expect(row("style_2.safetensors").querySelector("[data-hidden-preview]")).toBeTruthy();
    expect(row("style_2.safetensors").textContent).toContain("modelNsfwBadge");
  });
});

describe("把触发词加进提示词", () => {
  it("接在末尾、用逗号隔开;已经有的不重复加(不分大小写)", () => {
    expect(withTriggerWords("1girl, smile", ["1girl", "Watercolor"])).toBe("1girl, smile, Watercolor");
    expect(withTriggerWords("", ["a", "b"])).toBe("a, b");
    expect(withTriggerWords("a cat,  ", ["watercolor"])).toBe("a cat, watercolor");
    expect(withTriggerWords("WATERCOLOR style", ["watercolor"])).toBe("WATERCOLOR style");
  });
});
