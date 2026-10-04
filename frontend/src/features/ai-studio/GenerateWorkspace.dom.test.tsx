/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 生成工作台的两件事:
 *
 * - 同事**共享来的**会话只能看(后端 generation/sessions 定的,`is_mine: false` 是它给的答案):输入区换成一句
 *   只读说明,模型与参数栏不开、也不会把模型 PATCH 到别人的会话上;左栏那一行没有右键菜单、选不进批量删。
 * - 失败卡读**生成记录自己**存的失败原因:任务被「清空已结束」删掉之后(job_id 为空、任务列表里没有它),
 *   原因还在。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { readHint } from "@/test/hint";

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
  localStorage.setItem("mosael:tab:ai-studio", "generate");
});

const IMAGE_OPTION = {
  id: "p1:image:gpt-image-1",
  provider_profile_id: "p1",
  profile_name: "OpenAI",
  provider: "openai",
  kind: "image",
  model: "gpt-image-1",
  label: "OpenAI · gpt-image-1",
  capabilities: { modes: ["text-to-image"], parameter_keys: [] },
  capabilities_known: true,
  adapter_available: true,
  is_default: true,
};

function session(isMine: boolean) {
  return {
    id: "s1",
    workspace_id: "w1",
    title: "同事的海报",
    kind: "image",
    provider_profile_id: "their-profile",
    model: "gpt-image-1",
    is_mine: isMine,
    shared: true,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

function renderStudio({ isMine = true, generations = [] as unknown[] } = {}) {
  const writes: Array<{ url: string; method: string }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") {
      writes.push({ url, method: init.method });
      return json({});
    }
    if (url.includes("/api/generation/options?kind=image")) return json([IMAGE_OPTION]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([session(isMine)]);
    if (url.includes("/api/generation/jobs")) return json(generations);
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

describe("共享来的会话只能看", () => {
  it("输入区换成只读说明,模型与参数栏不开", async () => {
    renderStudio({ isMine: false });
    expect(await screen.findByRole("note")).toHaveTextContent("generationSessionReadOnly");
    expect(screen.queryByRole("textbox", { name: "genPromptLabel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "generate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "generationEngineSettings" })).toBeNull();
    // 参数栏收起(测试环境不加载样式表,看的是它挂着 hidden)。
    expect(screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true })).toHaveClass("hidden");
  });

  it("左栏那一行没有右键菜单(改名、收纳、删除都是主人的事),也选不进批量删", async () => {
    const { writes } = renderStudio({ isMine: false });
    const row = await screen.findByRole("button", { name: /同事的海报/ });
    expect(await readHint(row)).toContain("generationSessionReadOnly");
    fireEvent.contextMenu(row);
    expect(screen.queryByRole("menuitem", { name: /rename/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /delete/ })).toBeNull();
    // 能管的一条都没有:多选进不去。
    expect(screen.getByRole("button", { name: "mediaSelectMode" })).toBeDisabled();
    expect(writes).toEqual([]);
  });

  it("自己的会话照旧:有输入框、有参数栏、右键能改名", async () => {
    renderStudio({ isMine: true });
    expect(await screen.findByRole("textbox", { name: "genPromptLabel" })).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByRole("complementary", { name: "generationEngineSettings" })).not.toHaveClass("hidden");
    const row = await screen.findByRole("button", { name: /同事的海报/ });
    fireEvent.contextMenu(row);
    expect(await screen.findByRole("menuitem", { name: /rename/ })).toBeInTheDocument();
  });
});

describe("失败原因读生成记录自己的", () => {
  it("任务已经被清掉:照样说得出为什么失败", async () => {
    renderStudio({
      generations: [
        {
          id: "g1",
          workspace_id: "w1",
          session_id: "s1",
          job_id: null,
          provider_profile_id: "p1",
          provider: "openai",
          model: "gpt-image-1",
          kind: "image",
          request: { prompt: "一张海报" },
          result_asset_id: null,
          result_asset_ids: [],
          error: "供应商 openai 还没有配置你的密钥,请先在设置里填写",
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:01:00Z",
          costs: [],
          cost_confidence: null,
        },
      ],
    });
    expect(await screen.findByText("generationFailedTitle")).toBeInTheDocument();
    expect(screen.getAllByText("供应商 openai 还没有配置你的密钥,请先在设置里填写").length).toBeGreaterThan(0);
    expect(screen.queryByText("genFailed")).toBeNull();
    // 用户气泡只画他说的话。
    expect(screen.getByText("一张海报")).toBeInTheDocument();
  });

  it("记录上没有原因的老记录:说「生成失败」,不猜", async () => {
    renderStudio({
      generations: [
        {
          id: "g1",
          workspace_id: "w1",
          session_id: "s1",
          job_id: null,
          provider: "openai",
          model: "gpt-image-1",
          kind: "image",
          request: { prompt: "一张海报" },
          result_asset_id: null,
          result_asset_ids: [],
          error: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:01:00Z",
          costs: [],
          cost_confidence: null,
        },
      ],
    });
    await waitFor(() => expect(screen.getByText("genFailed")).toBeInTheDocument());
  });
});
