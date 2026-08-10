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

const models = [
  { id: "f5-tts", label: "F5-TTS", detail: "d", status: "missing", runtime_ready: false,
    downloaded_bytes: 0, total_bytes: 0, expected_bytes: 1_500_000_000, speed_bps: 0,
    eta_seconds: null, message: "未下载", needs_source: false, source_ready: false, source_dir: "" },
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

    const button = await screen.findByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("没动过就不该说「改了还没保存」", async () => {
    renderSection();

    await screen.findByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.queryByText(/ttsSaveFirst/)).toBeNull());
  });
});


describe("已保存 fish-speech + modelscope(用户库里的真实那一行)", () => {
  it("老值 modelscope 落到等价的 HuggingFace 上,而不是一片空白", async () => {
    config.engine = "fish-speech";
    config.source = "modelscope";
    (window as any).__DEBUG_TTS__ = true;
    renderSection();

    await screen.findByRole("button", { name: /asrModelDownload/ });
    // 触发器上显示的就是它 —— 不是一片空白。(下拉项本身也叫这个名字,所以用 getAllBy。)
    await waitFor(() => expect(screen.getAllByText("HuggingFace").length).toBeGreaterThan(0));
  });

  it("一个字没动,就不该是「改了还没保存」—— 否则每次刷新都要重存一遍", async () => {
    config.engine = "fish-speech";
    config.source = "modelscope";
    (window as any).__DEBUG_TTS__ = true;
    renderSection();

    await screen.findByRole("button", { name: /asrModelDownload/ });
    await waitFor(() => expect(screen.queryByText(/ttsSaveFirst/)).toBeNull());
  });
});
