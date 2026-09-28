/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 设置 → 配音与音色 → 内置配音引擎:只读地说哪几个不用连接就能配音。
 *
 * 本地克隆没装时,出路因人而异 —— 装引擎只给部署管理员,入口在管理页「引擎」。成员这里不该有一个
 * 跳进他打不开的页、或一点就 403 的按钮。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { BuiltinTtsSection } from "./BuiltinTtsSection";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const ENGINES = [
  { id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], note: "还没装", ready: false },
  { id: "edge", label: "Edge TTS", needs_key: false, needs_voice_id: false, voices: [], note: "免费", ready: true },
  { id: "openai", label: "OpenAI", needs_key: true, needs_voice_id: false, voices: [], note: "", ready: true },
];

function renderSection({ admin }: { admin: boolean }) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/auth/me") ? { is_deployment_admin: admin } : url.includes("/tts/engines") ? ENGINES : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BuiltinTtsSection />
    </QueryClientProvider>,
  );
}

describe("内置配音引擎", () => {
  it("只列不用连接的;就绪的写「即开即用」", async () => {
    renderSection({ admin: false });
    expect(await screen.findByText("Edge TTS")).toBeInTheDocument();
    expect(screen.queryByText("OpenAI")).toBeNull();
    expect(screen.getByText("builtinTtsReady")).toBeInTheDocument();
  });

  it("本地克隆没装、看的人是成员:说由部署管理员安装,没有按钮", async () => {
    renderSection({ admin: false });
    expect(await screen.findByText("engineInstalledByAdmin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "engineGoInstall" })).toBeNull();
  });

  it("本地克隆没装、看的人是部署管理员:一个按钮直达管理页「引擎」", async () => {
    const user = userEvent.setup();
    const opened: string[] = [];
    const listener = (event: Event) => opened.push(String((event as CustomEvent).detail));
    window.addEventListener("mosael:open-admin", listener);
    renderSection({ admin: true });
    await user.click(await screen.findByRole("button", { name: "engineGoInstall" }));
    await waitFor(() => expect(opened).toContain("engines"));
    window.removeEventListener("mosael:open-admin", listener);
  });
});
