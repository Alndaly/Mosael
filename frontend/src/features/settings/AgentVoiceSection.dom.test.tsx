/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「语音对话」关着的时候改引擎、音色、语速,只是改配置 —— 不能顺手把开关打开。
 * 此前自动保存写的是 `enabled || true`,恒为 true:关掉之后调一下语速,它又自己开了。
 */

const saved = {
  engine: "edge",
  engine_voice: "zh-CN-XiaoxiaoNeural",
  engine_voice_resource: "",
  engine_model: "",
  provider_profile_id: null,
  voice_id: null,
  speed: 1,
  enabled: false,
};
let pref = saved;
const setAgentVoice = vi.fn();
const fetchAgentVoicePreview = vi.fn();
const playSpeech = vi.fn();

vi.mock("@/api/client", () => ({
  getAgentVoice: () => Promise.resolve(pref),
  listTtsEngines: () => Promise.resolve([{ id: "edge", label: "Edge", ready: true }]),
  listTtsVoices: () => Promise.resolve([{ value: "zh-CN-XiaoxiaoNeural", label: "晓晓" }]),
  setAgentVoice: (body: unknown) => setAgentVoice(body),
  fetchAgentVoicePreview: (body: unknown) => fetchAgentVoicePreview(body),
}));
vi.mock("@/lib/speechPlayback", () => ({ playSpeech: (blob: Blob) => playSpeech(blob), stopSpeaking: () => {} }));
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

describe("试听", () => {
  beforeEach(() => {
    pref = saved;
    fetchAgentVoicePreview.mockReset();
    playSpeech.mockReset();
  });

  it("开关关着也能试听:试听是决定打开之前听一下效果", async () => {
    const audio = new Blob(["ID3"], { type: "audio/mpeg" });
    fetchAgentVoicePreview.mockResolvedValue(audio);
    playSpeech.mockResolvedValue(undefined);
    renderSection();
    const preview = await screen.findByRole("button", { name: "voicePreview" });
    await waitFor(() => expect(preview).toBeEnabled());
    expect(screen.getByRole("switch", { name: "agentVoiceEnabled" })).not.toBeChecked();

    await userEvent.setup().click(preview);
    await waitFor(() => expect(playSpeech).toHaveBeenCalledWith(audio));
    expect(fetchAgentVoicePreview).toHaveBeenCalledWith({ workspace_id: "ws-1", text: "agentVoiceSample" });
  });

  it("还没选好音色时试听是灰的,并说出为什么", async () => {
    pref = { ...saved, engine_voice: "" };
    renderSection();
    const preview = await screen.findByRole("button", { name: "voicePreview" });
    await waitFor(() => expect(screen.getByRole("switch", { name: "agentVoiceEnabled" })).toBeDisabled());
    expect(preview).toBeDisabled();
    expect(preview).toHaveAttribute("title", "agentVoicePreviewNeedsVoice");
  });
});
