/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 「Qwen3-TTS 装好之后,到底在哪儿切到它」——这条测试替用户走一遍那条路。
 *
 * 维护者装好 Qwen3-TTS 后在「管理 → 引擎 → 声音克隆」里找它:那一节中间只有一个「引擎」下拉,
 * 装好的 Qwen3-TTS 就写在它底下。可那个下拉存的是**默认克隆引擎**(F5-TTS / Fish Speech,
 * 后端 `TtsConfigUpdate` 只收这两个),Qwen3-TTS 是预置音色引擎(不克隆),它不该、也不能
 * 出现在那里 —— 塞进去会让「声音克隆」撒谎,后端还会 422。
 *
 * 能切到它的地方是**配音/合成**的引擎选择器(剪辑台「配音」、创作页「语音」)。这条测试钉住
 * 三件事:选项里有它、选了它不会冒出克隆那几格(参考音频/克隆音色)、交出去的请求就是
 * `builtin:qwentts` + `engine_voice`,不带 `voice_id`、不带语速(Qwen 没有语速参数)。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

//: 后端 `GET /api/tts/engines` 的真实形状(2026-10-20 实际响应,只留这条测试要的字段)。
const QWEN = {
  id: "builtin:qwentts",
  label: "Qwen3-TTS(本机)",
  needs_key: false,
  needs_voice_id: false,
  voices: ["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"],
  supports_speed: false,
  note: "本机运行,不联网、不花钱;9 个预置音色,不需要参考音频。",
  ready: true,
  clones_voices: false,
};
const CLONE = {
  id: "builtin:clone",
  label: "本地音色克隆",
  needs_key: false,
  needs_voice_id: false,
  voices: [],
  supports_speed: true,
  note: "",
  ready: true,
  clones_voices: false,
};
/** 后端按目录翻好的音色:9 个预置音色(`source: "preset"`)—— 一把克隆音色都没有。 */
const QWEN_VOICES = [
  ["vivian", "Vivian(女·明亮)"],
  ["serena", "Serena(女·温柔)"],
  ["uncle_fu", "傅叔叔(男·低沉)"],
  ["dylan", "Dylan(男·京腔)"],
  ["eric", "Eric(男·川渝)"],
  ["ryan", "Ryan(男·英文)"],
  ["aiden", "Aiden(男·美音)"],
  ["ono_anna", "音乃安娜(女·日语)"],
  ["sohee", "Sohee(女·韩语)"],
].map(([id, label]) => voiceOption(id, label, { source: "preset" }));

vi.mock("@/api/client", () => ({
  getTtsConfig: () =>
    Promise.resolve({
      engine: "f5-tts",
      python_path: "",
      pip_index: "",
      fish_repo_dir: "",
      fish_model_dir: "",
      worker_ready: true,
      worker_python: "/x/python",
      worker_checked: true,
    }),
  listTtsEngines: () => Promise.resolve([CLONE, QWEN]),
  listTtsModels: () =>
    Promise.resolve([
      { id: "f5-tts", label: "F5-TTS", detail: "d", status: "installed", runtime_ready: true, runtime_checked: true },
      { id: "qwen-tts", label: "Qwen3-TTS", detail: "d", status: "installed", runtime_ready: true, runtime_checked: true },
    ]),
  listTtsVoices: () => Promise.resolve(QWEN_VOICES),
  listVoices: () => Promise.resolve([]),
}));

import { SpeechVoiceFields } from "./SpeechVoiceFields";
import { useSpeechVoice } from "./useSpeechVoice";
import { voiceOption } from "@/test/voiceOption";

function Harness() {
  const voice = useSpeechVoice("w1");
  return (
    <div>
      <SpeechVoiceFields voice={voice} />
      <pre data-testid="params">{JSON.stringify(voice.params)}</pre>
      <pre data-testid="chosen">{JSON.stringify(voice.voiceChoices)}</pre>
      <button type="button" onClick={() => voice.setEngineVoice("vivian")}>
        pick-vivian
      </button>
    </div>
  );
}

function renderHarness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

describe("Qwen3-TTS 在配音/合成的引擎选择器里", () => {
  it("选项里有它,选了之后音色是模型的 9 个预置音色", async () => {
    const user = userEvent.setup();
    renderHarness();

    const picker = await screen.findByRole("combobox", { name: "voiceEngine" });
    await waitFor(() => expect(picker).toHaveTextContent("本地音色克隆"));
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Qwen3-TTS(本机)" }));

    await waitFor(() => expect(picker).toHaveTextContent("Qwen3-TTS(本机)"));
    // 音色是模型自带的 9 个,不是配音库里的克隆音色。
    const chosen = JSON.parse(screen.getByTestId("chosen").textContent ?? "[]");
    expect(chosen).toHaveLength(9);
    expect(chosen.every((one: { source: string }) => one.source === "preset")).toBe(true);
  });

  it("选了它不会要求参考音频/克隆音色 —— 那是克隆引擎才有的两格", async () => {
    const user = userEvent.setup();
    renderHarness();

    const picker = await screen.findByRole("combobox", { name: "voiceEngine" });
    await waitFor(() => expect(picker).toHaveTextContent("本地音色克隆"));
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Qwen3-TTS(本机)" }));

    await waitFor(() => expect(screen.queryByLabelText("voicePanelCloneEngine")).toBeNull());
    expect(screen.queryByLabelText("voiceLibraryPick")).toBeNull();
  });

  it("交出去的请求是 qwentts + engine_voice,不带 voice_id / clone_engine / speed", async () => {
    const user = userEvent.setup();
    renderHarness();

    const picker = await screen.findByRole("combobox", { name: "voiceEngine" });
    await waitFor(() => expect(picker).toHaveTextContent("本地音色克隆"));
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: "Qwen3-TTS(本机)" }));
    await waitFor(() => expect(picker).toHaveTextContent("Qwen3-TTS(本机)"));

    const params = JSON.parse(screen.getByTestId("params").textContent ?? "{}");
    // 引擎 id 就是能力表里的 `builtin:qwentts`;音色是预置音色的 id,默认落到第一个(vivian)。
    expect(params.engine).toBe("builtin:qwentts");
    expect(params.engine_voice).toBe("vivian");
    // **不带参考音频**:qwen 这条路上没有 `voice_id`(克隆音色)、也没有克隆引擎那两格。
    expect(params).not.toHaveProperty("voice_id");
    expect(params).not.toHaveProperty("clone_engine");
    expect(params).not.toHaveProperty("clone_model");
    // Qwen3-TTS 的 API 没有语速参数 —— 摆一个拨不动的旋钮比不摆更糟。
    expect(params).not.toHaveProperty("speed");
  });
});
