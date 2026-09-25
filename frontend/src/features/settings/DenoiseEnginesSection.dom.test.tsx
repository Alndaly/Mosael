/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 设置 → 降噪:一页看全所有方式,只有要下载的那个有按钮。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { DenoiseEnginesSection } from "@/features/settings/DenoiseEnginesSection";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const BASE = { installable: false, status: "ready", setup_hint: "", message: "", size_bytes: 0, strengths: [] };
const rows = (deepfilter: Record<string, unknown>) => [
  { ...BASE, engine: "ffmpeg", label: "内置降噪", description: "去底噪", ready: true, removes_music: false },
  {
    ...BASE, engine: "deepfilternet", label: "DeepFilterNet", description: "效果最好", ready: false,
    installable: true, status: "missing", size_bytes: 27_877_081, removes_music: true, ...deepfilter,
  },
  { ...BASE, engine: "rnnoise", label: "RNNoise", description: "轻量;**背景音乐也会被当成噪声去掉**", ready: false, status: "unavailable", setup_hint: "ffmpeg 不带这个滤镜", removes_music: true },
];

function renderSection(deepfilter: Record<string, unknown> = {}) {
  const posts: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      posts.push(url);
      return new Response(JSON.stringify(rows({ status: "installing" })[1]), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify(rows(deepfilter)), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DenoiseEnginesSection />
    </QueryClientProvider>,
  );
  return { posts };
}

const rowOf = async (label: string) => (await screen.findByText(label)).closest("div.rounded-lg") as HTMLElement;

describe("降噪引擎设置页", () => {
  it("只有要下载的那个有下载按钮,点了就装", async () => {
    const user = userEvent.setup();
    const { posts } = renderSection();
    const deepfilter = await rowOf("DeepFilterNet");
    expect(within(deepfilter).getByText(/denoiseSizeApprox/)).toBeInTheDocument();
    await user.click(within(deepfilter).getByRole("button", { name: /denoiseInstall/ }));
    await waitFor(() => expect(posts).toEqual(["/api/denoise/engines/deepfilternet/install"].map((path) => expect.stringContaining(path))));
    expect(within(await rowOf("内置降噪")).queryByRole("button")).toBeNull();
  });

  it("会去掉音乐的标出来,不需要装但用不了的说清原因", async () => {
    renderSection();
    const rnnoise = await rowOf("RNNoise");
    expect(rnnoise).toHaveTextContent("denoiseRemovesMusicBadge");
    expect(rnnoise).toHaveTextContent("ffmpeg 不带这个滤镜");
    expect(rnnoise).toHaveTextContent("denoiseUnavailableLabel");
    expect(await rowOf("内置降噪")).not.toHaveTextContent("denoiseRemovesMusicBadge");
  });

  it("失败原因原样显示,按钮变成重试", async () => {
    renderSection({ status: "failed", message: "下载到的文件校验不符" });
    const deepfilter = await rowOf("DeepFilterNet");
    expect(deepfilter).toHaveTextContent("下载到的文件校验不符");
    expect(within(deepfilter).getByRole("button", { name: /denoiseRetry/ })).toBeInTheDocument();
  });

  it("这个平台没有发布文件时直说,不摆按钮", async () => {
    renderSection({ status: "unsupported" });
    const deepfilter = await rowOf("DeepFilterNet");
    expect(deepfilter).toHaveTextContent("denoiseUnsupported");
    expect(within(deepfilter).queryByRole("button")).toBeNull();
  });

  it("装好了显示已安装", async () => {
    renderSection({ status: "installed", ready: true });
    expect(await rowOf("DeepFilterNet")).toHaveTextContent("denoiseInstalled");
  });
});

it("引擎说明里的 **强调** 渲染成粗体,不露星号", async () => {
  renderSection();
  const row = await rowOf("RNNoise");
  expect(within(row).getByText("背景音乐也会被当成噪声去掉").tagName).toBe("STRONG");
  expect(row.textContent).not.toContain("**");
});
