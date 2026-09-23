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

const BASE = { installable: false, status: "ready", setup_hint: "", message: "", size_bytes: 0 };
const BUILTIN = { ...BASE, engine: "ffmpeg", label: "内置降噪", description: "去底噪,不动音乐", ready: true, strengths: ["light", "medium", "strong"], removes_music: false };
const RNNOISE = { ...BASE, engine: "rnnoise", label: "RNNoise", description: "轻量语音降噪", ready: true, strengths: ["light", "medium", "strong"], removes_music: true };
//: 没有档位的引擎 —— 界面不认识引擎,只看它声明了什么。
const UNTIERED = { ...BASE, engine: "single", label: "单档引擎", description: "只有一种处理", ready: true, strengths: [], removes_music: false };
const DEEPFILTER = {
  ...BASE, engine: "deepfilternet", label: "DeepFilterNet", description: "效果最好", ready: false, installable: true,
  status: "missing", setup_hint: "先去设置里下载", strengths: ["light", "medium", "strong"], removes_music: true,
};

function renderDialog(engines: object[] = [BUILTIN, RNNOISE]) {
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
    // 会去掉音乐的排在前面也不该被默认选中 —— 用户说"降噪"时没想把配乐也去掉。
    const { posts, onClose } = renderDialog([RNNOISE, BUILTIN]);
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

  it("会去掉音乐的标出来", async () => {
    const user = userEvent.setup();
    const { posts } = renderDialog();
    const rnnoise = await screen.findByRole("radio", { name: /RNNoise/ });
    expect(rnnoise).toHaveTextContent("denoiseRemovesMusicBadge");
    expect(await screen.findByRole("radio", { name: /内置降噪/ })).not.toHaveTextContent("denoiseRemovesMusicBadge");
    await user.click(rnnoise);
    await user.click(screen.getByRole("button", { name: "denoiseStart" }));
    await waitFor(() => expect(posts[0]?.body).toEqual({ engine: "rnnoise", strength: "medium" }));
  });

  it("没有档位的引擎不摆强度", async () => {
    const user = userEvent.setup();
    renderDialog([BUILTIN, UNTIERED]);
    expect(await screen.findByRole("radiogroup", { name: "denoiseStrength" })).toBeInTheDocument();
    await user.click(await screen.findByRole("radio", { name: /单档引擎/ }));
    expect(screen.queryByRole("radiogroup", { name: "denoiseStrength" })).toBeNull();
  });

  it("没准备好的方式点不了,显示引擎自己给的提示和说明", async () => {
    renderDialog([BUILTIN, DEEPFILTER]);
    const deepfilter = await screen.findByRole("radio", { name: /DeepFilterNet/ });
    expect(deepfilter).toBeDisabled();
    //: 提示在单选项下面单独一栏(不跟着变灰),读屏仍把它念成这个选项的说明。
    expect(deepfilter).toHaveAccessibleDescription("先去设置里下载");
    expect(deepfilter).toHaveTextContent("效果最好");
  });

  it("有要下载的引擎没装时,给一个去设置的入口", async () => {
    const user = userEvent.setup();
    const opened: string[] = [];
    const listener = (event: Event) => opened.push(String((event as CustomEvent).detail));
    window.addEventListener("mosael:open-settings", listener);
    const { onClose } = renderDialog([BUILTIN, DEEPFILTER]);
    await user.click(await screen.findByRole("button", { name: /denoiseGoDownload/ }));
    expect(onClose).toHaveBeenCalled();
    //: 深链事件是延迟发的(等设置页挂载),所以等它到。
    await waitFor(() => expect(opened).toContain("denoise"));
    window.removeEventListener("mosael:open-settings", listener);
  });

  it("都装好了就不摆这个入口", async () => {
    renderDialog([BUILTIN, { ...DEEPFILTER, ready: true, status: "installed" }]);
    await screen.findByRole("radio", { name: /DeepFilterNet/ });
    expect(screen.queryByRole("button", { name: /denoiseGoDownload/ })).toBeNull();
  });
});
