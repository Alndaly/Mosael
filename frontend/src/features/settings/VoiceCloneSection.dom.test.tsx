/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 「改了还没保存」必须真的是改了。
 *
 * 我给这一页加了一条闸:表单有未保存改动时挡住「下载」,免得用户换了下载源没保存就去点重试、
 * 跑的还是旧源。闸本身是对的,但实现是 `form.setValue(...)` —— 而 react-hook-form 的
 * `isDirty` 是拿当前值和**默认值**比的,`shouldDirty: false` 挡不住这个比较。
 *
 * 于是:已保存的源是 modelscope、引擎是 F5-TTS 时,进页面就会被那条兼容处理改成 hf,
 * 表单立刻"脏"了,而用户一个字都没动 —— 「下载」永久点不动,还挂着一句他看不懂的提示。
 *
 * 一条本来用来防止误操作的闸,变成了谁也过不去的墙。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const config = {
  engine: "f5-tts",
  python_path: "",
  // 关键:已保存的是 modelscope,而 F5-TTS 的下拉里没有这一项(它对 F5 没有意义)。
  source: "modelscope",
  pip_index: "",
  fish_repo_dir: "",
  fish_model_dir: "",
  worker_ready: true,
  worker_python: "/x/python",
};

const base = {
  detail: "d", status: "missing", runtime_ready: false, downloaded_bytes: 0, total_bytes: 0,
  speed_bps: 0, eta_seconds: null, message: "未下载", needs_source: false, source_ready: false, source_dir: "",
};
// 每个引擎能用哪些下载源由后端给 —— ModelScope 上没有 F5 要的 vocos,所以 F5 没有它。
const models = [
  { ...base, id: "f5-tts", label: "F5-TTS", expected_bytes: 1_500_000_000, sources: ["hf", "hf-mirror"] },
  { ...base, id: "fish-speech", label: "Fish Speech", expected_bytes: 11_000_000_000,
    sources: ["hf", "hf-mirror", "modelscope"] },
];

vi.mock("@/api/client", () => ({
  getTtsConfig: () => Promise.resolve(config),
  updateTtsConfig: () => Promise.resolve(config),
  listTtsModels: () => Promise.resolve(models),
  downloadTtsModel: () => Promise.resolve(models[0]),
}));

import { VoiceCloneSection } from "@/features/settings/VoiceCloneSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VoiceCloneSection />
    </QueryClientProvider>,
  );
}

describe("声音克隆设置", () => {
  it("刚进页面、一个字没动时,下载点得动", async () => {
    renderSection();

    const [button] = await screen.findAllByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("没动过就不该说「改了还没保存」", async () => {
    renderSection();

    await screen.findAllByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.queryByText(/ttsSaveFirst/)).toBeNull());
  });
});


describe("已保存 fish-speech + modelscope(用户库里的真实那一行)", () => {
  it("显示得出「ModelScope」,而不是一片空白 —— 它对 Fish Speech 是真的源", async () => {
    config.engine = "fish-speech";
    config.source = "modelscope";
    renderSection();

    await screen.findAllByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.getAllByText("ModelScope").length).toBeGreaterThan(0));
  });

  it("引擎不支持的源落到该引擎的第一个源上,而不是空白", async () => {
    config.engine = "f5-tts"; // ModelScope 上没有它要的 vocos
    config.source = "modelscope";
    renderSection();

    await screen.findAllByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.getAllByText("HuggingFace").length).toBeGreaterThan(0));
    expect(screen.queryByText("ModelScope")).toBeNull();
  });

  it("一个字没动,就不该是「改了还没保存」—— 否则每次刷新都要重存一遍", async () => {
    config.engine = "fish-speech";
    config.source = "modelscope";
    (window as any).__DEBUG_TTS__ = true;
    renderSection();

    await screen.findAllByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.queryByText(/ttsSaveFirst/)).toBeNull());
  });
});
