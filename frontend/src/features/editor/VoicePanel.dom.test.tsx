/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

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

const localEngines = [
  { id: "f5-tts", label: "F5-TTS", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: true },
  { id: "fish-speech", label: "Fish Speech S2 Pro", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: false },
];

function renderPanel(voiceData = voices) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/tts/models")
      ? localEngines
      : url.includes("/api/settings/tts")
        ? { engine: "f5-tts", python_path: "", source: "modelscope" }
        : url.includes("/tts/engines")
          ? [
              { id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], note: "clone note", ready: true },
              { id: "edge", label: "Edge TTS", needs_key: false, needs_voice_id: false, voices: [], ready: true },
            ]
          : url.includes("/tts/voices")
            ? [{ value: "edge-voice", label: "Edge Voice" }]
          : url.includes("/api/voices")
            ? voiceData
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
  it("空音色使用禁用控件和紧凑空状态,不在生成按钮下堆提示", async () => {
    renderPanel([]);

    expect(await screen.findByPlaceholderText("voiceLibraryPickEmpty")).toBeDisabled();
    const emptyTitle = await screen.findByText("voiceLibraryEmpty");
    const emptyState = emptyTitle.closest(".empty-state");
    expect(emptyState).not.toBeNull();
    expect(emptyState!.className).toContain("max-w-none!");
    expect(emptyState!.className).not.toMatch(/border-dashed|bg-background/);
    expect(screen.getByText("voiceEmpty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceFromSpeaker" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceUpload" })).toBeInTheDocument();
    expect(screen.queryByText("voiceNeedVoice")).not.toBeInTheDocument();
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
