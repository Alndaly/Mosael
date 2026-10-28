/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

/**
 * 「语音对话」关着的时候改引擎、音色、语速,只是改配置 —— 不能顺手把开关打开。
 * 此前自动保存写的是 `enabled || true`,恒为 true:关掉之后调一下语速,它又自己开了。
 */

const saved = {
  //: 存着的那把嗓子(ADR 0087 的音色选择);null = 没选。
  voice: { engine: "builtin:edge", voice: "zh-CN-XiaoxiaoNeural" } as { engine: string; voice: string } | null,
  speed: 1,
  enabled: false,
  //: 说话输入的引擎。空 = 跟随转写默认(此前听写没有自己的开关)。
  asr_engine: "",
  //: 念回复时先出声(默认)。
  speak_early: true,
};
let pref = saved;
const setAgentVoice = vi.fn();
const fetchAgentVoicePreview = vi.fn();
const playBlob = vi.fn();

/** 转写的候选(能力表):只有 missing 为空的那几家能选。`current` 是这个人在「能力提供方」定过的。 */
let personalTranscription: string | null = null;
const transcriptionChoices = () => [{
  capability: "transcription",
  label: "转写",
  description: "",
  current: personalTranscription,
  automatic: "builtin:funasr",
  defaultable: true,
  options: [
    { id: "builtin:funasr", name: "FunASR(本机)", builtin: true, missing: [] },
    { id: "builtin:whisperx", name: "WhisperX(本机)", builtin: true, missing: [] },
    { id: "builtin:sherpa-onnx", name: "sherpa-onnx(本机,轻量)", builtin: true, missing: ["缺运行环境"] },
  ],
  used_by: [],
}];

/** 转写模型目录:只为了把「跟随转写」写得具体(管理里设的默认是哪一个)。 */
let defaultAsrModel: string | null = "WhisperX Large v3";

vi.mock("@/api/client", () => ({
  getAgentVoice: () => Promise.resolve(pref),
  listTtsEngines: () => Promise.resolve([{ id: "edge", label: "Edge", ready: true }]),
  listTtsVoices: () => Promise.resolve([{ value: "zh-CN-XiaoxiaoNeural", label: "晓晓" }]),
  listCapabilityChoices: () => Promise.resolve(transcriptionChoices()),
  listAsrModels: () =>
    Promise.resolve([
      { id: "whisperx-large-v3", engine: "whisperx", label: defaultAsrModel ?? "", is_default: Boolean(defaultAsrModel) },
    ]),
  setAgentVoice: (body: unknown) => setAgentVoice(body),
  fetchAgentVoicePreview: (body: unknown) => fetchAgentVoicePreview(body),
}));
vi.mock("@/lib/audioPlayback", () => ({ playBlob: (blob: Blob) => playBlob(blob), stopPlayback: () => {} }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ voiceDock: false, setVoiceDock: () => {} }),
}));

import { AgentVoiceSection } from "./AgentVoiceSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentVoiceSection workspaceId="ws-1" />
    </QueryClientProvider>,
  );
}

describe("语音对话的自动保存", () => {
  beforeEach(() => {
    pref = saved;
    setAgentVoice.mockReset();
    setAgentVoice.mockResolvedValue(pref);
    Element.prototype.scrollIntoView = vi.fn();
    Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {} });
  });

  it("关着时改语速:存下新语速,开关仍是关的", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByRole("switch", { name: "agentVoiceEnabled" })).toBeTruthy());
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "agentVoiceSpeed" }));
    await user.click(await screen.findByRole("option", { name: "1.5×" }));

    await waitFor(() => expect(setAgentVoice).toHaveBeenCalledTimes(1));
    expect(setAgentVoice.mock.calls[0][0]).toMatchObject({ speed: 1.5, enabled: false });
  });
});

describe("说话输入用哪一家", () => {
  beforeEach(() => {
    pref = saved;
    defaultAsrModel = "WhisperX Large v3";
    setAgentVoice.mockReset();
    //: 回包就是存下的那份(和后端一样):状态跟着服务端走,不会因为测试桩回旧值而反复保存。
    setAgentVoice.mockImplementation(async (body: Record<string, unknown>) => ({ ...saved, ...body }));
    Element.prototype.scrollIntoView = vi.fn();
    Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {} });
  });

  it("默认跟随转写,只列就绪的转写候选", async () => {
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    expect(trigger.textContent).toContain("agentVoiceDictationFollow");

    const user = userEvent.setup();
    await user.click(trigger);
    expect(await screen.findByRole("option", { name: "WhisperX(本机)" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "FunASR(本机)" })).toBeTruthy();
    //: 缺运行环境的候选不出现 —— 列出来只会让人选中之后才失败。
    expect(screen.queryByRole("option", { name: "sherpa-onnx(本机,轻量)" })).toBeNull();
  });

  it("「跟随转写」写着默认是哪一份 —— 不是一张空白卡片", async () => {
    defaultAsrModel = "WhisperX Large v3";
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await waitFor(() => expect(trigger.textContent).toContain("WhisperX Large v3"));
  });

  it("没设过默认时只说跟随转写,不编一个名字", async () => {
    defaultAsrModel = null;
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await waitFor(() => expect(trigger.textContent).toBe("agentVoiceDictationFollow"));
  });

  it("个人在能力提供方定过转写默认时,「跟随」显示的是那一项(它比部署默认更具体)", async () => {
    personalTranscription = "builtin:whisperx";
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await waitFor(() => expect(trigger.textContent).toContain("WhisperX(本机)"));
    personalTranscription = null;
  });

  it("选中即存;重进这一页还在", async () => {
    const view = renderSection();
    const user = userEvent.setup();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await user.click(trigger);
    await user.click(await screen.findByRole("option", { name: "WhisperX(本机)" }));

    await waitFor(() => expect(setAgentVoice).toHaveBeenCalled());
    expect(setAgentVoice.mock.calls.at(-1)?.[0]).toMatchObject({ asr_engine: "builtin:whisperx", enabled: false });

    //: 重进页面 = 用服务端此刻存着的那份重新挂载。
    view.unmount();
    pref = { ...saved, asr_engine: "builtin:whisperx" };
    renderSection();
    const reopened = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await waitFor(() => expect(reopened.textContent).toContain("WhisperX(本机)"));
  });
  it("重进页面时不会把存着的那一格又写回去", async () => {
    pref = { ...saved, asr_engine: "builtin:whisperx" };
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "agentVoiceDictationEngine" });
    await waitFor(() => expect(trigger.textContent).toContain("WhisperX(本机)"));
    //: 水合那一帧 asrEngine 还是初始的空串;把它当成「用户选回了跟随转写」就会在每次打开页面时
    //: 悄悄清掉服务端存着的选择。
    expect(setAgentVoice).not.toHaveBeenCalled();
  });
});

describe("念回复时先出声", () => {
  beforeEach(() => {
    pref = saved;
    setAgentVoice.mockReset();
    setAgentVoice.mockImplementation(async (body: Record<string, unknown>) => ({ ...saved, ...body }));
    Element.prototype.scrollIntoView = vi.fn();
    Object.assign(Element.prototype, { hasPointerCapture: () => false, setPointerCapture: () => {}, releasePointerCapture: () => {} });
  });

  it("默认先出声;选等整段会把 speak_early:false 存下去", async () => {
    renderSection();
    const early = await screen.findByRole("radio", { name: "agentVoiceSpeakEarlyEarly" });
    expect(early).toHaveAttribute("aria-checked", "true");

    await userEvent.setup().click(screen.getByRole("radio", { name: "agentVoiceSpeakEarlyWhole" }));

    await waitFor(() => expect(setAgentVoice).toHaveBeenCalled());
    expect(setAgentVoice.mock.calls.at(-1)?.[0]).toMatchObject({ speak_early: false, enabled: false });
  });

  it("重进页面时按服务端存着的那一档显示", async () => {
    pref = { ...saved, speak_early: false };
    renderSection();
    const whole = await screen.findByRole("radio", { name: "agentVoiceSpeakEarlyWhole" });
    await waitFor(() => expect(whole).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByRole("radio", { name: "agentVoiceSpeakEarlyEarly" })).toHaveAttribute("aria-checked", "false");
    expect(setAgentVoice).not.toHaveBeenCalled();
  });
});

describe("试听", () => {
  beforeEach(() => {
    pref = saved;
    fetchAgentVoicePreview.mockReset();
    playBlob.mockReset();
  });

  it("开关关着也能试听:试听是决定打开之前听一下效果", async () => {
    const audio = new Blob(["ID3"], { type: "audio/mpeg" });
    fetchAgentVoicePreview.mockResolvedValue(audio);
    playBlob.mockResolvedValue(undefined);
    renderSection();
    // 灰着时按钮外面多一层说明原因的壳,能点了壳就拿掉 —— 按钮会换一个元素,所以每次都重新找。
    await waitFor(() => expect(screen.getByRole("button", { name: "voicePreview" })).toBeEnabled());
    const preview = screen.getByRole("button", { name: "voicePreview" });
    expect(screen.getByRole("switch", { name: "agentVoiceEnabled" })).not.toBeChecked();

    await userEvent.setup().click(preview);
    await waitFor(() => expect(playBlob).toHaveBeenCalledWith(audio));
    expect(fetchAgentVoicePreview).toHaveBeenCalledWith({ workspace_id: "ws-1", text: "agentVoiceSample" });
  });

  it("还没选好音色时试听是灰的,并说出为什么", async () => {
    pref = { ...saved, voice: null };
    renderSection();
    const preview = await screen.findByRole("button", { name: "voicePreview" });
    await waitFor(() => expect(screen.getByRole("switch", { name: "agentVoiceEnabled" })).toBeDisabled());
    expect(preview).toBeDisabled();
    expect(await readHint(preview)).toBe("voicePreviewagentVoicePreviewNeedsVoice");
  });
});
