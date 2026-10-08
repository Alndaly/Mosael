/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 表单是工作流的入口(ADR 0045 第一步),在 AI Studio 里看到的样子。维护者:krea2-text-2-image.json 上做了表单「快速用krea2生图」,
 * 之后到处只叫表单名 —— 认不出是哪张工作流,也拿不到全部参数。现在同一张工作流两项:
 *
 * - 下拉里是一小组(第二步,ADR 0045 §7):小标题写工作流名和哪台服务器,下面「完整工作流」和表单各一行(缩进);没有表单的
 *   照旧一行、第二行连接名。搜「快速」整组留着、命中的表单那行加粗,搜「krea2」两个都在;
 * - 右栏那张表的标题下面写着来自哪张工作流、哪台服务器;选完整工作流,右栏是全部参数(不是那张表)。
 *
 * 断言画出来的字,不只看数据。
 */

vi.mock("@/app/preferences", () => {
  //: 文案照键名;两层名字的副名那两句给真话
  const said: Record<string, string> = { entryFromGroup: "来自 {name}", entryFullWorkflow: "完整工作流" };
  return {
    useI18n: () => (key: string) => said[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
});

const SERVER = "ComfyUI · http://192.168.3.15:8188";
const GROUP = { id: "krea2-text-2-image.json", label: "krea2-text-2-image" };

/** 完整工作流:全部能填的项(这里是步数、画幅)。 */
const FULL = {
  id: "p9:image:krea2-text-2-image.json", provider_profile_id: "p9", plugin_instance_id: "i9", profile_name: SERVER,
  provider: "plugin:dev.mosael.comfyui", kind: "image", model: "krea2-text-2-image.json", model_label: "krea2-text-2-image",
  group: { ...GROUP, entry: "full", order: 0 },
  capabilities: {
    modes: ["text-to-image"], parameter_keys: ["3.steps", "10.aspect_ratio"], prompt: "optional",
    parameter_schema: {
      "3.steps": { type: "integer", title: "步数", default: 8 },
      "10.aspect_ratio": { type: "string", title: "画幅", enum: ["1:1", "9:16"], default: "9:16" },
    },
  },
  capabilities_known: true, adapter_available: true, is_default: false,
};

/** 表单入口:只露画幅,作者起了名字。 */
const FORM = {
  ...FULL,
  id: "p9:image:krea2-text-2-image.json#app", model: "krea2-text-2-image.json#app", model_label: "快速用krea2生图",
  group: { ...GROUP, entry: "form", order: 1 }, is_default: true,
  capabilities: {
    modes: ["text-to-image"], parameter_keys: ["10.aspect_ratio"], prompt: "optional",
    parameter_schema: { "10.aspect_ratio": { type: "string", title: "画幅", enum: ["1:1", "9:16"], default: "9:16" } },
    form: { title: "快速用krea2生图", description: "", items: [{ key: "prompt", label: "提示词" }, { key: "10.aspect_ratio", label: "画幅" }] },
  },
};

const OTHER = {
  id: "p1:image:gpt-image-1", provider_profile_id: "p1", plugin_instance_id: "", profile_name: "OpenAI", provider: "openai",
  kind: "image", model: "gpt-image-1", model_label: "gpt-image-1", group: null,
  capabilities: { modes: ["text-to-image"], parameter_keys: [] }, capabilities_known: true, adapter_available: true, is_default: false,
};

function renderStudio() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") return json({});
    if (url.includes("/api/generation/options?kind=image")) return json([OTHER, FULL, FORM]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([]);
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
}

async function openPicker(panel: HTMLElement) {
  const trigger = await waitFor(() => {
    const found = panel.querySelector<HTMLElement>("[data-engine-picker] button");
    expect(found).not.toBeNull();
    return found!;
  });
  fireEvent.click(trigger);
  return await waitFor(() => {
    const input = document.querySelector<HTMLInputElement>("input[cmdk-input]");
    expect(input).not.toBeNull();
    return input!;
  });
}

describe("同一张工作流的完整工作流和表单:一小组,名字分两层", () => {
  it("下拉里一小组:小标题工作流名 + 连接名,下面「完整工作流」和表单;按表单标题、工作流名都搜得到", async () => {
    renderStudio();
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    const search = await openPicker(panel);
    const form = await screen.findByRole("option", { name: /快速用krea2生图/ });
    const full = screen.getByRole("option", { name: /^完整工作流/ });
    const head = document.querySelector("[data-section-head]") as HTMLElement;
    expect(head.textContent, "小标题:工作流名和哪台服务器").toBe(`krea2-text-2-image${SERVER}`);
    expect(form).toHaveAttribute("data-indent");
    expect(full).toHaveAttribute("data-indent");
    expect(form.getAttribute("data-section")).toBe(full.getAttribute("data-section"));
    expect(screen.getByRole("option", { name: /^gpt-image-1/ }).textContent, "没有表单、不属于哪一组:照旧一行,第二行只有连接名")
      .toBe("gpt-image-1OpenAI");
    const names = () => screen.getAllByRole("option").map((one) => one.textContent ?? "");
    expect(names().indexOf("完整工作流") + 1, "表单紧挨着它的完整工作流").toBe(names().indexOf("快速用krea2生图"));

    fireEvent.change(search, { target: { value: "快速" } });
    await waitFor(() => expect(names(), "搜表单标题:整组留着").toEqual(["完整工作流", "快速用krea2生图"]));
    expect(screen.getByRole("option", { name: /快速用krea2生图/ }), "命中的那行加粗").toHaveAttribute("data-hit");
    fireEvent.change(search, { target: { value: "krea2" } });
    await waitFor(() => expect(names()).toHaveLength(2));
  });

  it("右栏那张表下面写着来自哪张工作流;选完整工作流,右栏是全部参数", async () => {
    renderStudio();
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    await waitFor(() => expect(panel.textContent).toContain("genAppFormSection"));
    const head = panel.querySelector<HTMLElement>("[data-app-form-head]")!;
    expect(head.textContent).toContain("快速用krea2生图");
    expect(within(head).getByText(`来自 krea2-text-2-image · ${SERVER}`)).toBeTruthy();
    expect(panel.textContent, "表单只露画幅").not.toContain("步数");

    await openPicker(panel);
    fireEvent.click(await screen.findByRole("option", { name: /^完整工作流/ }));
    await waitFor(() => expect(panel.textContent).not.toContain("genAppFormSection"));
    expect(panel.textContent, "完整工作流:全部能填的项").toContain("步数");
    expect(panel.textContent).toContain("画幅");
    const chip = document.querySelector<HTMLElement>("[data-engine-chip]")!;
    expect(chip.textContent, "输入框底下那枚按钮只写主名").toBe("krea2-text-2-image");
  });
});
