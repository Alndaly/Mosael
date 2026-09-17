/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

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
import { useEditorStore } from "@/stores/editorStore";

const voices = [{ id: "v1", name: "我的", reference_text: "", source: "upload", created_at: "2026-01-01T00:00:00Z", has_reference: true }];

// jsdom 没有 Pointer Capture,而 Radix 的 Select 在 pointerdown 里就要用它 —— 不补上,
// 展开下拉这件事在测试里根本做不到(它会抛 `hasPointerCapture is not a function`)。
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
beforeEach(() => useEditorStore.getState().selectClip(null));

const localEngines = [
  { id: "f5-tts", label: "F5-TTS", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: true },
  { id: "fish-speech", label: "Fish Speech S2 Pro", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: false },
];

//: 默认只装了中英基础模型 —— 这台机器上最常见的样子,也是「日文念不了」的那个前提。
const BASE_WEIGHTS = [
  { id: "base", label: "基础模型", languages: ["zh", "en"], installed: true, status: "installed", expected_bytes: 1e9, progress: 1, message: "", note: "" },
  { id: "ja", label: "日语模型", languages: ["ja"], installed: false, status: "missing", expected_bytes: 1.4e9, progress: 0, message: "", note: "" },
];

function sequenceWith(texts: string[]) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "subtitle",
        clips: texts.map((text, index) => ({
          id: `c${index}`, asset_id: null, asset_kind: "", timeline_start: index * 5, src_in: 0, src_out: 3, speed: 1, text_override: text,
        })),
      },
    ],
  } as never;
}

type Served = { voices?: unknown[]; texts?: string[]; weights?: unknown[]; onOpenSubtitles?: () => void };

function renderPanel({ voices: voiceData = voices, texts = ["一条字幕"], weights = BASE_WEIGHTS, onOpenSubtitles }: Served = {}) {
  const dubRequests: Array<Record<string, unknown>> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/dub-subtitles")) {
      dubRequests.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    const body = url.includes("/tts/f5-models")
      ? weights
      : url.includes("/api/tts/models")
        ? localEngines
        : url.includes("/api/settings/tts")
          ? { engine: "f5-tts", python_path: "", source: "modelscope" }
          : url.includes("/tts/engines")
            ? [
                { id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], note: "clone note", ready: true },
                { id: "edge", label: "Edge TTS", needs_key: false, needs_voice_id: false, voices: [], ready: true },
                { id: "volcano-podcast", label: "火山播客", needs_key: true, needs_voice_id: false, voices: [], ready: true },
              ]
            : url.includes("/tts/voices")
              ? [{ value: "edge-voice", label: "Edge Voice" }]
              : url.includes("/api/voices")
                ? voiceData
                : url.includes("/api/jobs/")
                  ? { id: "job-1", status: "running" }
                  : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <VoicePanel
        workspace={{ id: "w1", name: "W" } as never}
        project={{ id: "p1" } as never}
        sequence={sequenceWith(texts)}
        onOpenSubtitles={onOpenSubtitles}
      />
    </QueryClientProvider>,
  );
  return { ...view, dubRequests };
}

describe("音色库", () => {
  it("空音色使用禁用控件和紧凑空状态,不在生成按钮下堆提示", async () => {
    renderPanel({ voices: [] });

    expect(await screen.findByPlaceholderText("voiceLibraryPickEmpty")).toBeDisabled();
    const emptyTitle = await screen.findByText("voiceLibraryEmpty");
    const emptyState = emptyTitle.closest(".empty-state");
    expect(emptyState).not.toBeNull();
    expect(emptyState!.className).toContain("max-w-none!");
    expect(emptyState!.className).not.toMatch(/border-dashed|bg-background/);
    expect(screen.getByText("voiceEmpty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceFromSpeaker" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceUpload" })).toBeInTheDocument();
    expect(screen.queryByText("clone note")).not.toBeInTheDocument();
  });

  it("从说话人使用弹窗,不再挤开音色列表", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceFromSpeaker" }));

    expect(screen.getByRole("dialog", { name: "voiceFromSpeaker" })).toBeInTheDocument();
  });

  it("上传克隆使用带录音入口的弹窗", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceUpload" }));

    const dialog = screen.getByRole("dialog", { name: "voiceUpload" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceRecord" })).toBeInTheDocument();
    expect(dialog.querySelector('[data-slot="modal-footer"]')).not.toBeNull();
  });

  it("切换到远程语音引擎后隐藏本地音色库", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("voiceLibrary")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "voiceEngine" }));
    await user.click(await screen.findByRole("option", { name: "Edge TTS" }));

    await waitFor(() => expect(screen.queryByText("voiceLibrary")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "voiceFromSpeaker" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "voiceUpload" })).not.toBeInTheDocument();
  });

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

/**
 * 配音面板是**可拖宽的侧栏**,默认只有 250px 上下。把「克隆引擎 / 音色 / 语速」写成
 * `grid-cols-[1fr_1fr_88px]` 之后,引擎那一格实测只剩 65px —— 触发器显示成「F5-…」,
 * 展开的菜单被 SelectContent 的 `max-w-[trigger-width]` 一起压成 60px,两个选项变成
 * 「F5…」「Fi…」。**一个读不出选项的选择器等于没有这个功能**,而它正是这一轮加的。
 *
 * 根因不是"列宽给少了",是**用固定列数去排一个宽度会变的容器**:换成 3 列同样会在别的
 * 宽度上错。所以这里的判据是"这一行按内容需要换行",而不是"这一行是几列"。
 */
describe("配音面板的控件行(响应式)", () => {
  it("克隆的那一行会换行,而不是写死列数把每格挤成 65px", async () => {
    renderPanel();
    const picker = await screen.findByRole("combobox", { name: "voicePanelCloneEngine" });

    const row = picker.closest("div.flex-wrap");

    expect(row, "克隆引擎所在的行不会换行 —— 面板一窄就把三个控件挤成看不清的宽度").not.toBeNull();
    expect(row!.className, "行里还留着写死的列轨道").not.toMatch(/grid-cols-\[/);
  });

  it("引擎名有下限宽度 —— 它是这一行里最长的一个,不能被平均分配", async () => {
    renderPanel();
    const picker = await screen.findByRole("combobox", { name: "voicePanelCloneEngine" });

    const field = picker.closest("div.flex-wrap")!.querySelector<HTMLElement>(":scope > div");

    expect(field!.className).toMatch(/min-w-\[/);
  });

  it("两个引擎都在下拉里,没装好的标出来", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("combobox", { name: "voicePanelCloneEngine" }));

    expect(await screen.findByRole("option", { name: "Fish Speech S2 Pro" })).toBeInTheDocument();
  });
});

/**
 * 给字幕配音 —— 原先是字幕页里的一个弹层,现在就是这一页的主表单。
 *
 * 1. **双语字幕要能选念哪一行**:翻译勾了「保留原文」之后,一条字幕是「原文\n译文」;整段丢给合成
 *    就是先念一遍原文再念一遍译文。这个选择**只在真有双语时出现**。
 * 2. **范围跟着时间线上的选中走** —— 字幕页每行的入口就是"选中它、切过来"。
 * 3. 语言对不上当场说,并把缺的那份权重的下载放在手边。
 */
describe("给字幕配音", () => {
  it("双语字幕才问「念哪一行」", async () => {
    renderPanel({ texts: ["The.\n这。"] });
    expect(await screen.findByRole("combobox", { name: "subtitleDubLine" })).toBeInTheDocument();
  });

  it("单语字幕不问 —— 那个选择在这里没有意义", async () => {
    renderPanel({ texts: ["只有一行"] });
    await screen.findByRole("button", { name: /subtitleDubApply/ });
    expect(screen.queryByRole("combobox", { name: "subtitleDubLine" })).toBeNull();
  });

  it("播客引擎不在可选引擎里 —— 它一次产出整段对话,在「AI 生成 → 音频」", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("combobox", { name: "voiceEngine" }));
    expect(await screen.findByRole("option", { name: "Edge TTS" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "火山播客" })).toBeNull();
  });

  it("时间线上选中了几条,就只配那几条", async () => {
    useEditorStore.getState().selectClip("c1");
    const user = userEvent.setup();
    const { dubRequests } = renderPanel({ texts: ["第一条", "第二条"] });
    expect(await screen.findByText("subtitleTranslateSelectedOnly")).toBeInTheDocument();
    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);
    await waitFor(() => expect(dubRequests).toHaveLength(1));
    expect(dubRequests[0]).toMatchObject({ clip_ids: ["c1"], engine: "clone", voice_id: "v1", clone_engine: "f5-tts", speed: 1 });
  });

  it("日文字幕 + 本地克隆:当场说缺哪份权重,并把下载放在手边", async () => {
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"] });
    expect(await screen.findByText(/subtitleDubModelMissing/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "subtitleDubModelDownload" })).toBeInTheDocument();
  });

  it("日语权重装上之后,提示和下载入口一起消失", async () => {
    const weights = BASE_WEIGHTS.map((model) => ({ ...model, installed: true, status: "installed" }));
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"], weights });
    // 两份权重都装了,「用哪份」的下拉出现 —— 说明权重清单已经到了,判断是基于它做的。
    expect(await screen.findByRole("combobox", { name: "subtitleDubWeights" })).toBeInTheDocument();
    expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull();
  });

  it("Fish Speech 不拿 F5 的权重清单判语言 —— 它一份模型念多语", async () => {
    const user = userEvent.setup();
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"] });
    await screen.findByText(/subtitleDubModelMissing/);
    await user.click(screen.getByRole("combobox", { name: "voicePanelCloneEngine" }));
    await user.click(await screen.findByRole("option", { name: "Fish Speech S2 Pro" }));
    await waitFor(() => expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull());
  });

  it("中文字幕不触发警告 —— 一条错误的警告会让人开始怀疑所有警告", async () => {
    renderPanel({ texts: ["这是中文字幕"] });
    await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull());
  });

  it("缩放到段落长度默认关 —— 变速会改语速听感,值不值由用户按素材定", async () => {
    renderPanel();
    const toggle = await screen.findByRole("switch");
    expect(toggle.getAttribute("data-state")).toBe("unchecked");
  });

  it("时间线上没有字幕:说清楚,并给一个去字幕页的按钮", async () => {
    const onOpenSubtitles = vi.fn();
    const user = userEvent.setup();
    renderPanel({ texts: [], onOpenSubtitles });
    await user.click(await screen.findByRole("button", { name: /subtitleDubOpenSubtitles/ }));
    expect(onOpenSubtitles).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /subtitleDubApply/ })).toBeNull();
  });
});
