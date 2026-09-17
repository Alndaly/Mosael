/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * AI 生成 → 音频:念一段文字、做一期播客。产物进素材库,不碰时间线。
 *
 * 钉住的是这几件:两种请求各自发到对的路由、带对的字段;没配好时说去哪儿配,而不是摆一张
 * 点了必然失败的表单;「最近生成」只列这一种产物。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AudioWorkspace } from "@/features/ai-studio/AudioWorkspace";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
beforeEach(() => localStorage.clear());

const ENGINES = [
  { id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], ready: true },
  { id: "edge", label: "Edge TTS", needs_key: false, needs_voice_id: false, voices: [], ready: true },
  { id: "volcano-podcast", label: "火山播客", needs_key: true, needs_voice_id: false, voices: [], ready: true },
];

const ASSETS = [
  { id: "a1", name: "念出来的", kind: "audio", source: "tts", created_at: "2026-09-01T00:00:00Z", workspace_id: "w1", project_id: null, original_filename: "", file_key: "k", media_info: {} },
  { id: "a2", name: "一期播客", kind: "audio", source: "podcast", created_at: "2026-09-02T00:00:00Z", workspace_id: "w1", project_id: null, original_filename: "", file_key: "k", media_info: {} },
  { id: "a3", name: "导入的歌", kind: "audio", source: "imported", created_at: "2026-09-03T00:00:00Z", workspace_id: "w1", project_id: null, original_filename: "", file_key: "k", media_info: {} },
];

function renderWorkspace({ engines = ENGINES, voices = [] as unknown[] } = {}) {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    const body = url.includes("/tts/engines")
      ? engines
      : url.includes("/tts/voices?engine=volcano-podcast")
        ? [{ value: "host-a", label: "主持人 A" }, { value: "host-b", label: "主持人 B" }]
        : url.includes("/tts/voices")
          ? [{ value: "edge-voice", label: "Edge Voice" }]
          : url.includes("/api/tts/models")
            ? [{ id: "f5-tts", label: "F5-TTS", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: true }]
            : url.includes("/api/settings/tts")
              ? { engine: "f5-tts" }
              : url.includes("/api/voices")
                ? voices
                : url.includes("/api/assets")
                  ? ASSETS
                  : url.includes("/api/jobs/")
                    ? { id: "job-1", status: "running" }
                    : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AudioWorkspace workspace={{ id: "w1", name: "W" } as never} />
    </QueryClientProvider>,
  );
  return { posts };
}

describe("语音", () => {
  it("远端引擎:发到 /tts/synthesize,带上显示着的发音人", async () => {
    const user = userEvent.setup();
    const { posts } = renderWorkspace();
    await user.click(await screen.findByRole("combobox", { name: "voiceEngine" }));
    await user.click(await screen.findByRole("option", { name: "Edge TTS" }));
    await user.type(screen.getByRole("textbox", { name: "voiceSynthPlaceholder" }), "你好");
    const generate = screen.getByRole("button", { name: /voiceGenerate/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await user.click(generate);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/api/tts/synthesize");
    expect(posts[0].body).toMatchObject({ workspace_id: "w1", text: "你好", engine: "edge", engine_voice: "edge-voice" });
    // 这一页不绑项目 —— 产物是工作区级的素材。
    expect(posts[0].body.project_id).toBeUndefined();
  });

  it("本地克隆还没有音色:说去哪儿建,生成按钮不可点", async () => {
    renderWorkspace({ voices: [] });
    expect(await screen.findByRole("button", { name: /audioManageVoices/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /voiceGenerate/ })).toBeDisabled();
  });

  it("「最近生成」只列念出来的,不混进播客和导入的", async () => {
    renderWorkspace();
    const recent = await screen.findByRole("region", { name: "audioRecentTitle" });
    expect(await within(recent).findByText("念出来的")).toBeInTheDocument();
    expect(within(recent).queryByText("一期播客")).toBeNull();
    expect(within(recent).queryByText("导入的歌")).toBeNull();
  });
});

describe("播客", () => {
  async function openPodcast() {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: /audioModePodcast/ }));
    return user;
  }

  it("默认两个不同的发音人,生成时一起发出去", async () => {
    const { posts } = renderWorkspace();
    const user = await openPodcast();
    await user.type(await screen.findByRole("textbox", { name: "audioPodcastTextPlaceholder" }), "一段材料");
    const generate = screen.getByRole("button", { name: /voiceGenerate/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await user.click(generate);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/api/tts/podcast");
    expect(posts[0].body).toMatchObject({ mode: "summarize", text: "一段材料", topic: "", speakers: ["host-a", "host-b"] });
  });

  it("没配播客服务:给去配置的入口,不摆表单", async () => {
    renderWorkspace({ engines: ENGINES.filter((engine) => engine.id !== "volcano-podcast") });
    await openPodcast();
    expect(await screen.findByRole("button", { name: /audioConfigurePodcast/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /voiceGenerate/ })).toBeNull();
  });

  it("「最近生成」切到播客的产物", async () => {
    renderWorkspace();
    await openPodcast();
    const recent = await screen.findByRole("region", { name: "audioRecentTitle" });
    expect(await within(recent).findByText("一期播客")).toBeInTheDocument();
    expect(within(recent).queryByText("念出来的")).toBeNull();
  });
});
