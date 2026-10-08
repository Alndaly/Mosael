/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 维护者在 AI 工作台生成页一口气报的几件事(2026-10-07):
 *
 * - 「发起了怎么就没办法取消/停止了」:在跑、在排的那一条有「停止」,点了取消它的任务(任务总线的 cancel);停下的那一条说
 *   「已停止」,不是一张红色的失败卡;
 * - 「loading 的这个卡片 UI 也很丑」:在跑的那一条按产出的样子占位(几张、什么比例),下面一行写排队中 / 生成中、进度、
 *   插件报的那一句、已用多久;
 * - 「点击底部这个 ComfyUI 开头的这一串没有任何反应」:栏开着时点它也要有反应 —— 焦点落到右栏的模型选择上;
 * - 「右侧引擎参数配置明显和实际的精简表单不符」:有精简表单的工作流,右栏就是那张表(标题、说明、表上的每一项,按表上的顺序和
 *   名字;主提示词说明就是下面的输入框,可以不写时说不写用哪一句)。
 */

vi.mock("@/app/preferences", () => ({
  //: 文案照键名;带 {prompt} 的那一句留着占位,看得出填进去的是哪一句
  useI18n: () => (key: string) => (key === "genFormPromptStored" ? `${key}:{prompt}` : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));

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
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
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
  //: 上次开着的是 s1(没选过会话时停在「新的一条」,不落进最近那条,见 UC-03)
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
});

const COMFY = {
  id: "p9:image:slow.json",
  provider_profile_id: "p9",
  plugin_instance_id: "i9",
  profile_name: "ComfyUI · http://127.0.0.1:8391",
  provider: "plugin:dev.mosael.comfyui",
  kind: "image",
  model: "slow.json",
  model_label: "慢速出图",
  label: "ComfyUI · http://127.0.0.1:8391 · 慢速出图",
  capabilities: { modes: ["text-to-image"], parameter_keys: [] },
  capabilities_known: true,
  adapter_available: true,
  is_default: true,
};

/** 一张精简表单:主提示词 + 一项「画幅」(作者起的名字),工作流里存着一句提示词;表外还有一项「结果取自」。 */
const WITH_FORM = {
  ...COMFY,
  capabilities: {
    modes: ["text-to-image"],
    parameter_keys: ["output_node", "10.aspect_ratio"],
    parameter_schema: {
      output_node: { type: "string", title: "结果取自", enum: ["all", "9"], default: "all" },
      "10.aspect_ratio": { type: "string", title: "画幅", enum: ["1:1", "9:16"], default: "9:16" },
    },
    prompt: "optional",
    prompt_default: "湖边的清晨,薄雾",
    form: {
      title: "快速用krea2生图",
      description: "只写一句话就能出图",
      items: [
        { key: "prompt", label: "提示词" },
        { key: "10.aspect_ratio", label: "画幅" },
      ],
    },
  },
};

function session() {
  return {
    id: "s1", workspace_id: "w1", title: "测试", kind: "image", provider_profile_id: "p9", model: "slow.json",
    is_mine: true, shared: false, created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:00Z",
  };
}

function generation(extra: Record<string, unknown> = {}) {
  return {
    id: "g1", workspace_id: "w1", session_id: "s1", job_id: "j1", provider_profile_id: "p9",
    provider: "plugin:dev.mosael.comfyui", model: "slow.json", kind: "image",
    request: { prompt: "湖边", parameters: { size: "512x768" } }, result_asset_id: null, result_asset_ids: [], error: null,
    stopped: false, created_at: new Date(Date.now() - 42_000).toISOString(), updated_at: new Date().toISOString(),
    costs: [], cost_confidence: null, ...extra,
  };
}

function job(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: "j1", workspace_id: "w1", kind: "ai_generation", status, progress: 0.35, message: "Mosael Slow Render · 第 2/3 个节点",
    payload: {}, result: {}, error: null, created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:10Z", ...extra,
  };
}

function renderStudio({ option = COMFY as unknown, generations = [] as unknown[], jobs = [] as unknown[] } = {}) {
  const writes: Array<{ url: string; method: string }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") {
      writes.push({ url, method: init.method });
      return json({});
    }
    if (url.includes("/api/generation/options?kind=image")) return json([option]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([session()]);
    if (url.includes("/api/generation/jobs")) return json(generations);
    if (url.includes("/api/jobs?")) return json(jobs);
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
  return { writes };
}

describe("在跑的那一条:按产出的样子占位,说清走到哪儿了,能停", () => {
  it("生成中:竖图的占位、进度、插件那一句、已用多久;「停止」取消它的任务", async () => {
    const { writes } = renderStudio({ generations: [generation()], jobs: [job("running")] });
    const status = await screen.findByRole("status", { name: "generating" });
    expect(status.getAttribute("data-generation-pending")).toBe("running");
    expect(status.textContent).toContain("35%");
    expect(status.textContent).toContain("Mosael Slow Render · 第 2/3 个节点");
    expect(status.textContent).toContain("usageRunning");
    //: 请求的是 512x768:占位是竖的 —— 一张最高 360px,宽 = 360 × 2/3 = 240px,不是一块方的灰块
    const frame = status.querySelector<HTMLElement>("[style*='width']")!;
    expect(frame.getAttribute("style")).toContain("min(240px, 100%)");
    expect(status.querySelector("[data-slot='skeleton'][data-surface]"), "在跑的扫光").not.toBeNull();
    fireEvent.click(within(status).getByRole("button", { name: /genStop/ }));
    await waitFor(() => expect(writes).toContainEqual({ url: expect.stringContaining("/api/jobs/j1/cancel"), method: "POST" }));
  });

  it("排队中:不扫光,说「排队中」和等了多久,照样能停", async () => {
    renderStudio({ generations: [generation()], jobs: [job("queued", { progress: 0, message: "" })] });
    const status = await screen.findByRole("status", { name: "genQueued" });
    expect(status.textContent).toContain("genQueuedFor");
    expect(status.querySelector("[data-slot='skeleton']"), "还没开始做:不扫光").toBeNull();
    expect(within(status).getByRole("button", { name: /genStop/ })).toBeInTheDocument();
  });

  it("停下的那一条说「已停止」,不是失败卡;花没花钱照脚注那一句", async () => {
    renderStudio({
      generations: [generation({ job_id: null, stopped: true, error: "已取消", cost_confidence: "not_billed" })],
    });
    const card = await waitFor(() => {
      const found = document.querySelector("[data-generation-stopped]");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(card.textContent).toContain("genStopped");
    expect(screen.queryByText("generationFailedTitle")).toBeNull();
    expect(card.closest("article")!.textContent).toContain("usageCostNotBilled");
    expect(screen.queryByRole("button", { name: /genStop/ }), "停下了就没有「停止」").toBeNull();
  });
});

describe("输入框底下那枚模型按钮", () => {
  it("栏开着时点它:焦点落到右栏的模型选择上,模型那一块亮一下 —— 不再是点了什么都不发生", async () => {
    renderStudio();
    const chip = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>("[data-engine-chip]");
      expect(found).not.toBeNull();
      return found!;
    });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings" });
    expect(panel).not.toHaveClass("hidden");
    expect(chip.hasAttribute("data-active"), "栏开着:按钮是按下的样子").toBe(true);
    expect(chip.getAttribute("aria-controls")).toBe(panel.id);
    fireEvent.click(chip);
    //: 亮一下只亮 1.2 秒(到点自己熄):点下去当场就亮,就在这里看 —— 不放到等焦点之后,免得和熄灯的计时器比谁先到。
    expect(panel.querySelector("[data-engine-section]")!.hasAttribute("data-flash")).toBe(true);
    const picker = panel.querySelector<HTMLElement>("[data-engine-picker] button")!;
    await waitFor(() => expect(document.activeElement).toBe(picker));
  });

  it("栏收着时点它:把栏打开,焦点照样过去", async () => {
    renderStudio();
    const chip = await waitFor(() => {
      const found = document.querySelector<HTMLButtonElement>("[data-engine-chip]");
      expect(found).not.toBeNull();
      return found!;
    });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    fireEvent.click(within(panel).getByRole("button", { name: "close" }));
    expect(panel).toHaveClass("hidden");
    expect(chip.hasAttribute("data-active")).toBe(false);
    fireEvent.click(chip);
    expect(panel).not.toHaveClass("hidden");
    await waitFor(() => expect(document.activeElement).toBe(panel.querySelector("[data-engine-picker] button")));
  });
});

describe("有精简表单的工作流:右栏就是那张表", () => {
  it("表的标题、说明,表上的每一项按表上的顺序和名字;主提示词指向输入框、说清不写用哪一句;表外的另起一栏", async () => {
    renderStudio({ option: WITH_FORM });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    await waitFor(() => expect(panel.textContent).toContain("快速用krea2生图"));
    expect(panel.textContent).toContain("只写一句话就能出图");
    expect(panel.textContent).toContain("genAppFormSection");
    const prompt = panel.querySelector<HTMLElement>("[data-form-prompt]")!;
    expect(prompt.textContent).toContain("提示词");
    expect(prompt.textContent).toContain("genFormPromptOptional");
    expect(prompt.textContent).toContain("湖边的清晨,薄雾");
    //: 表上的顺序:提示词在前、画幅在后
    const text = panel.textContent ?? "";
    expect(text.indexOf("提示词")).toBeLessThan(text.indexOf("画幅"));
    //: 表外的「结果取自」另起一栏,不混进表里;通用的那几栏(出片规格、素材、调参)不出现
    expect(text.indexOf("genAppFormMore")).toBeGreaterThan(text.indexOf("画幅"));
    expect(text.indexOf("结果取自")).toBeGreaterThan(text.indexOf("genAppFormMore"));
    expect(text).not.toContain("genSectionOutput");
    expect(text).not.toContain("genSectionAdvanced");
    //: 输入框的占位说的是同一件事
    const box = screen.getByRole("textbox", { name: "genPromptLabel" });
    expect(box.getAttribute("placeholder")).toBe("promptPlaceholderStored");
    //: 「把这句填进去改」:填进输入框、焦点过去
    fireEvent.click(within(prompt).getByRole("button", { name: "genFormPromptUseStored" }));
    expect(box).toHaveValue("湖边的清晨,薄雾");
    expect(document.activeElement).toBe(box);
  });

  it("没有表的照旧按参数分栏", async () => {
    renderStudio({ option: { ...COMFY, capabilities: { ...COMFY.capabilities, prompt: "optional" } } });
    const box = await screen.findByRole("textbox", { name: "genPromptLabel" });
    await waitFor(() => expect(box.getAttribute("placeholder"), "说不出不写用哪句:照旧那一句").toBe("promptPlaceholderOptional"));
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    expect(panel.querySelector("[data-form-prompt]")).toBeNull();
    expect(panel.textContent).not.toContain("genAppFormSection");
  });
});
