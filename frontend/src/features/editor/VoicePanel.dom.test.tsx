/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 点了那支笔要**真的打开**编辑表单。
 *
 * 用户报「点笔按钮没有任何用」。原因是我插入表单的那次字符串替换没匹配上锚点,而我**没加
 * 断言** —— 它静默地什么都没做。typecheck 照样过:`editing` 状态确实被按钮用着,只是没有
 * 任何东西读它。
 *
 * 这类"改了但没生效"靠类型检查抓不到,只有**按一下看看**能抓到。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { VoicePanel } from "@/features/editor/VoicePanel";

const voices = [{ id: "v1", name: "我的", reference_text: "", source: "upload", created_at: "2026-01-01T00:00:00Z", has_reference: true }];

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function renderPanel() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/voices") && !url.includes("tts")
      ? voices
      : url.includes("/tts/engines")
        ? [{ id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], note: "", ready: true }]
        : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VoicePanel workspace={{ id: "w1", name: "W" } as never} project={{ id: "p1" } as never} tabs={null} />
    </QueryClientProvider>,
  );
}

describe("音色库", () => {
  it("点铅笔打开编辑表单 —— 用户报的正是「点了没反应」", async () => {
    const user = userEvent.setup();
    renderPanel();
    const pencil = await screen.findByRole("button", { name: "voiceEdit" });

    await user.click(pencil);

    await waitFor(() => expect(screen.getByText("voiceEditHint")).toBeInTheDocument());
  });

  it("表单里能看到「自动识别」和「保存」", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceEdit" }));

    expect(screen.getByRole("button", { name: /voiceRecognizeReference/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/ })).toBeInTheDocument();
  });

  it("没填参考文本的音色要标出来 —— 它在下拉里看起来和别的一样正常", async () => {
    renderPanel();

    expect(await screen.findByText("voiceNoReferenceText")).toBeInTheDocument();
  });
});
