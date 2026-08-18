/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  detail: "d", status: "missing", runtime_ready: false, runtime_checked: true, downloaded_bytes: 0, total_bytes: 0,
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
    await waitFor(() => expect(screen.queryByText(/ttsSaveAndDownload/)).toBeNull());
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
    await waitFor(() => expect(screen.queryByText(/ttsSaveAndDownload/)).toBeNull());
  });
});


/**
 * 顶上的横幅和底下的卡片必须给**同一个答案**。
 *
 * 真机上抓到的一页:下拉里选 Fish Speech(还没保存),横幅红着说「『Fish Speech S2 Pro』
 * 尚未就绪,现在合成会被当场拒绝……点下方的『下载』即可」,而同一页底下那张卡写着
 * 「Fish Speech S2 Pro · 11.0 GB · 已安装」,后端 /api/tts/models 也回
 * `runtime_ready: true, message: "已安装,声音克隆可用"`。
 *
 * 根因:横幅问的是**配置级**的 `worker_ready`(后端只对「已保存」的那个引擎算),而
 * 「这个引擎跑不跑得起来」现在是**逐引擎**有答案的(models 里的 runtime_ready)。
 * 拿一个回答不了这个问题的来源去回答它,就只能得到"选了别的引擎 = 未就绪"这种假话 ——
 * 它会让人去下载一个已经躺在盘上的 11 GB 模型。
 */
describe("横幅说的是被选中那个引擎的真实状态", () => {
  beforeEach(() => {
    Object.assign(Element.prototype, {
      hasPointerCapture: () => false,
      setPointerCapture: () => {},
      releasePointerCapture: () => {},
      scrollIntoView: () => {},
    });
    config.engine = "f5-tts";
    config.source = "hf";
    config.worker_ready = true;
    models[0] = { ...base, id: "f5-tts", label: "F5-TTS", expected_bytes: 1_500_000_000, sources: ["hf", "hf-mirror"], status: "installed", runtime_ready: true, runtime_checked: true };
    models[1] = { ...base, id: "fish-speech", label: "Fish Speech", expected_bytes: 11_000_000_000, sources: ["hf", "hf-mirror", "modelscope"], status: "installed", runtime_ready: true, runtime_checked: true };
  });

  it("选了另一个装好的引擎(还没保存)时,不说它「尚未就绪」", async () => {
    const user = userEvent.setup();
    renderSection();
    const picker = await screen.findByRole("combobox", { name: "voiceCloneEngine" });

    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Fish Speech" }));

    await waitFor(() => expect(screen.queryByText(/voiceCloneNotReady/)).toBeNull());
  });

  it("那个引擎还没探完时说「正在检查」,不说「未就绪」—— 不知道不等于不行", async () => {
    models[0] = { ...models[0], runtime_checked: false, runtime_ready: false };
    renderSection();

    await waitFor(() => expect(screen.getAllByText(/runtimeChecking/).length).toBeGreaterThan(0));
    expect(screen.queryByText(/voiceCloneNotReady/)).toBeNull();
  });
});

describe("探测还没答完时", () => {
  it("卡片说「正在检查」,而不是说「未就绪」", async () => {
    models[0] = { ...models[0], status: "installed", runtime_checked: false, runtime_ready: false };
    renderSection();

    await waitFor(() => expect(screen.getAllByText(/runtimeChecking/).length).toBeGreaterThan(0));
    expect(screen.queryByText(/voiceModelNoRuntime/)).toBeNull();
  });

});

describe("改了设置之后点重试", () => {
  it("按钮不再因为「没保存」而点不动", async () => {
    // 真机反馈:F5-TTS 下载失败 → 想换个下载源再试 → 一改,「重试」就灰了,提示去页顶点保存。
    // 而改下载源**正是为了**重下 —— 意图很清楚,不该让他多走一步,更不该给一个点不动的按钮。
    models[0].status = "failed";
    models[0].message = "下载没有完成";
    renderSection();

    const [retry] = await screen.findAllByRole("button", { name: /asrModelRetry/ });
    // **真的把表单改脏** —— 不改的话 unsaved 本来就是 false,这条测试等于什么都没验。
    const python = await screen.findByPlaceholderText("/path/to/venv/bin/python");
    await userEvent.type(python, "/tmp/py");
    await waitFor(() => expect(screen.getAllByText(/ttsSaveAndDownload/).length).toBeGreaterThan(0));

    expect(retry).not.toBeDisabled();
  });
});
