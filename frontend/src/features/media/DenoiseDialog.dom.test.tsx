/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 降噪对话框:选"用哪种方式"和"下手多重"。
 *
 * 钉住的是:默认落在不去音乐的那种、默认中度;会去掉音乐的那种要说出来;没有档位的方式不摆
 * 那个旋钮;没准备好的方式点不了并说清去哪准备;提交的就是屏幕上选中的那两样。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { DenoiseDialog } from "@/features/media/DenoiseDialog";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const BUILTIN = { engine: "ffmpeg", label: "内置降噪", ready: true, strengths: ["light", "medium", "strong"], removes_music: false };
const ISOLATION = { engine: "voice-isolation", label: "人声提取", ready: true, strengths: [], removes_music: true };

function renderDialog(engines = [BUILTIN, ISOLATION]) {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify(url.includes("/denoise/engines") ? engines : []), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as never;
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DenoiseDialog assetId="a1" onClose={onClose} />
    </QueryClientProvider>,
  );
  return { posts, onClose };
}

describe("降噪对话框", () => {
  it("默认内置、中度,提交的就是这两样", async () => {
    const user = userEvent.setup();
    // 人声提取排在前面也不该被默认选中 —— 用户说"降噪"时没想把配乐也去掉。
    const { posts, onClose } = renderDialog([ISOLATION, BUILTIN]);
    expect(await screen.findByRole("radio", { name: /内置降噪/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "denoiseStrengthMedium" })).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("button", { name: "denoiseStart" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/api/assets/a1/denoise");
    expect(posts[0].body).toEqual({ engine: "ffmpeg", strength: "medium" });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("选了强力就发强力", async () => {
    const user = userEvent.setup();
    const { posts } = renderDialog();
    await user.click(await screen.findByRole("radio", { name: "denoiseStrengthStrong" }));
    await user.click(screen.getByRole("button", { name: "denoiseStart" }));
    await waitFor(() => expect(posts[0]?.body).toEqual({ engine: "ffmpeg", strength: "strong" }));
  });

  it("人声提取:说出会去掉音乐,且不摆强度", async () => {
    const user = userEvent.setup();
    const { posts } = renderDialog();
    const isolation = await screen.findByRole("radio", { name: /人声提取/ });
    expect(isolation).toHaveTextContent("denoiseRemovesMusic");
    await user.click(isolation);
    expect(screen.queryByRole("radiogroup", { name: "denoiseStrength" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "denoiseStart" }));
    await waitFor(() => expect(posts[0]?.body).toMatchObject({ engine: "voice-isolation" }));
  });

  it("没准备好的方式点不了,并说清去哪准备", async () => {
    renderDialog([BUILTIN, { ...ISOLATION, ready: false }]);
    const isolation = await screen.findByRole("radio", { name: /人声提取/ });
    expect(isolation).toBeDisabled();
    expect(isolation).toHaveTextContent("denoiseEngineUnready");
  });
});
