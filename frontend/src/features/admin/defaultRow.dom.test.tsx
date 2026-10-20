/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「默认」的摆放规则(维护者定的):**只出现在同一能力有多个可选实现的地方**,并且永远放在
 * 这些实现所在的那一节里 —— 节说明之后、实现列表之前。
 *
 * 这一组钉住四个决定:
 *   1. 那句话/那一行由**数据**决定:≥2 个候选才有默认行,只有 1 个则说清"没有默认可设";
 *   2. 位置统一:默认那条永远在说明之后、列表之前;
 *   3. 交互统一:ASR 和 TTS 都是**行内「设为默认」**,默认那一行是状态、不可点;TTS 的下拉不再存在
 *      (否则同一个默认有两处可写);
 *   4. 未安装的不能设默认,已默认的不能再点。
 *
 * 现实数据:ASR 目录有 5 个模型;TTS 的克隆组有 F5-TTS / Fish Speech 两个,预置组只有 Qwen3-TTS
 * 一个;人声分离只有 Demucs 一个。所以"只有一个候选"不是假想 —— 预置组和分离现在就长这样。
 */

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  return {
    useI18n: () => (key: string) => (zhCN as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const asrModel = (over: Record<string, unknown> = {}) => ({
  id: "funasr", engine: "funasr", label: "FunASR", detail: "中文识别", status: "installed",
  runtime_ready: true, runtime_checked: true, downloaded_bytes: 0, total_bytes: 0,
  expected_bytes: 973_000_000, total_is_estimate: false, speed_bps: 0, eta_seconds: null,
  message: "", is_default: false,
  ...over,
});

const ttsEngine = (over: Record<string, unknown> = {}) => ({
  id: "f5-tts", label: "F5-TTS", detail: "克隆", status: "installed", runtime_ready: true,
  runtime_checked: true, downloaded_bytes: 0, total_bytes: 0, expected_bytes: 1_500_000_000,
  total_is_estimate: true, speed_bps: 0, eta_seconds: null, message: "", needs_source: false,
  source_ready: false, source_dir: "", sources: ["hf"], supports_speed: false,
  ...over,
});

const separationEngine = (over: Record<string, unknown> = {}) => ({
  engine: "demucs", label: "Demucs", status: "installed", runtime_checked: true, message: "",
  ...over,
});

let asrModels: Array<Record<string, unknown>> = [];
let ttsModels: Array<Record<string, unknown>> = [];
let separationEngines: Array<Record<string, unknown>> = [];
let ttsConfig: Record<string, unknown> = {};
const updateTtsConfig = vi.fn();

vi.mock("@/api/client", () => ({
  listAsrModels: () => Promise.resolve(asrModels),
  downloadAsrModel: (id: string) => Promise.resolve(asrModels.find((one) => one.id === id)),
  setDefaultAsrModel: (id: string) => {
    asrModels = asrModels.map((one) => ({ ...one, is_default: one.id === id }));
    return Promise.resolve(asrModels.find((one) => one.id === id));
  },
  getTtsConfig: () => Promise.resolve(ttsConfig),
  updateTtsConfig: (body: Record<string, unknown>) => {
    updateTtsConfig(body);
    // 后端真的存下来了:再问一次配置时,新答案就是它。
    ttsConfig = { ...ttsConfig, ...body };
    return Promise.resolve(ttsConfig);
  },
  listTtsModels: () => Promise.resolve(ttsModels),
  downloadTtsModel: (id: string) => Promise.resolve(ttsModels.find((one) => one.id === id)),
  listSeparationEngines: () => Promise.resolve(separationEngines),
  installSeparationEngine: () => Promise.resolve(separationEngines[0]),
}));

import { AsrModelsSection } from "./AsrModelsSection";
import { SeparationEnginesSection } from "./SeparationEnginesSection";
import { VoiceCloneSection } from "./VoiceCloneSection";

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function section(id: string): HTMLElement {
  const node = document.querySelector(`[data-admin-section="${id}"]`);
  if (!(node instanceof HTMLElement)) throw new Error(`没有 ${id} 这一节`);
  return node;
}

function group(kind: "clone" | "preset"): HTMLElement {
  const node = document.querySelector(`[data-engine-group="${kind}"]`);
  if (!(node instanceof HTMLElement)) throw new Error(`没有 ${kind} 这一组`);
  return node;
}

/** 一条实现(一个引擎/模型)自己那一行 —— 默认行里也会出现引擎名,所以不能只按文字找。 */
function rowByLabel(scope: HTMLElement, label: string): HTMLElement {
  const row = [...scope.querySelectorAll<HTMLElement>("[data-admin-row]")].find((one) =>
    within(one).queryByText(label),
  );
  if (!row) throw new Error(`没有「${label}」那一行`);
  return row;
}

const DEFAULT_ONLY_ONE = "这一节只有一种引擎,所以没有默认可设。";
const SET_DEFAULT = "设为默认";
const ASR_DEFAULT = "默认模型";
const TTS_DEFAULT = "默认克隆引擎";

beforeEach(() => {
  asrModels = [];
  ttsModels = [];
  separationEngines = [];
  ttsConfig = {
    engine: "f5-tts", python_path: "", fish_repo_dir: "", fish_model_dir: "",
    worker_ready: true, worker_python: "/x/python", worker_checked: true,
  };
  updateTtsConfig.mockClear();
});

describe("转写模型:默认行跟着模型数量走", () => {
  it("多个模型 → 默认行在节说明之后、模型列表之前", async () => {
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const box = section("engine-transcribe");
    const line = box.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(line).not.toBeNull();
    expect(line!.dataset.defaultKind).toBe("choice");
    expect(line).toHaveTextContent(ASR_DEFAULT);
    expect(line).toHaveTextContent("FunASR");

    // 节说明(header 里的那句)之后、列表那一张卡之前。
    expect(line!.previousElementSibling).toBe(box.querySelector("header"));
    const card = line!.nextElementSibling as HTMLElement;
    expect(card.querySelector("[data-admin-row]")).not.toBeNull();
  });

  it("只有一个模型 → 没有默认可设:说那一句,也不摆「设为默认」/「默认模型」", async () => {
    asrModels = [asrModel({ id: "funasr", label: "FunASR" })];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("FunASR");

    const box = section("engine-transcribe");
    const line = box.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(line!.dataset.defaultKind).toBe("single");
    expect(line).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(within(box).queryByRole("button", { name: SET_DEFAULT })).toBeNull();
    expect(within(box).queryByText(ASR_DEFAULT)).toBeNull();
  });
});

describe("人声与背景音分离:只有一种引擎", () => {
  it("说清没有默认可设,而且那句话在说明之后、列表之前", async () => {
    separationEngines = [separationEngine()];
    renderWithClient(<SeparationEnginesSection />);
    await screen.findByText("Demucs");

    const box = section("engine-separation");
    const line = box.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(line!.dataset.defaultKind).toBe("single");
    expect(line).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(line!.previousElementSibling).toBe(box.querySelector("header"));
    expect(line!.nextElementSibling?.querySelector("[data-admin-row]")).not.toBeNull();
  });
});

describe("语音合成引擎:默认在克隆那一组、用行内「设为默认」", () => {
  beforeEach(() => {
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "fish-speech", label: "Fish Speech" }),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
    ttsConfig = {
      engine: "f5-tts", python_path: "", fish_repo_dir: "", fish_model_dir: "",
      worker_ready: true, worker_python: "/x/python", worker_checked: true,
    };
  });

  it("默认不再是一个下拉;默认行在克隆组说明之后、两行之前", async () => {
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    expect(screen.queryByRole("combobox", { name: TTS_DEFAULT })).toBeNull();

    const clone = group("clone");
    const line = clone.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(line!.dataset.defaultKind).toBe("choice");
    expect(line).toHaveTextContent(TTS_DEFAULT);
    expect(line).toHaveTextContent("F5-TTS");
    // 组说明之后、克隆引擎列表之前。
    expect(line!.previousElementSibling).toBe(clone.querySelector("h3")!.parentElement);
    expect(line!.nextElementSibling?.querySelector("[data-admin-row]")).not.toBeNull();

    // 预置音色那一组只有一种引擎 —— 它没有默认可设。
    const preset = group("preset");
    const note = preset.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(note!.dataset.defaultKind).toBe("single");
    expect(note).toHaveTextContent(DEFAULT_ONLY_ONE);
  });

  it("行内:已默认的那一行是状态、不可点;另一行的「设为默认」写进 TtsConfig.engine —— 只有这一处可写", async () => {
    const user = userEvent.setup();
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    const f5 = rowByLabel(clone, "F5-TTS");
    const fish = rowByLabel(clone, "Fish Speech");

    // 已默认 = 一枚状态,不是按钮。
    expect(within(f5).getByText(TTS_DEFAULT)).toHaveAttribute("data-admin-row-state");
    expect(within(f5).queryByRole("button", { name: SET_DEFAULT })).toBeNull();
    // 没有下拉:能写默认的只有行内那一处。
    expect(screen.queryByRole("combobox", { name: TTS_DEFAULT })).toBeNull();
    expect(within(clone).getAllByRole("button", { name: SET_DEFAULT })).toHaveLength(1);

    await user.click(within(fish).getByRole("button", { name: SET_DEFAULT }));

    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalledTimes(1));
    expect(updateTtsConfig).toHaveBeenCalledWith(
      expect.objectContaining({ engine: "fish-speech", python_path: "" }),
    );

    // 默认翻过去:原来的默认行变回「设为默认」,新的那一行标着默认。
    await waitFor(() => {
      expect(within(rowByLabel(group("clone"), "Fish Speech")).getByText(TTS_DEFAULT)).toBeInTheDocument();
    });
    const f5Now = rowByLabel(group("clone"), "F5-TTS");
    expect(within(f5Now).getByRole("button", { name: SET_DEFAULT })).toBeInTheDocument();
    expect(within(f5Now).queryByText(TTS_DEFAULT)).toBeNull();
  });

  it("还没装的克隆引擎不能设默认", async () => {
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "fish-speech", label: "Fish Speech", status: "missing", runtime_ready: false }),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const fish = rowByLabel(group("clone"), "Fish Speech");
    expect(within(fish).queryByRole("button", { name: SET_DEFAULT })).toBeNull();
  });

  it("克隆引擎只剩一种时也不摆默认 —— 与「≥2 才有默认」同一条规则", async () => {
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    const line = clone.querySelector<HTMLElement>("[data-admin-default-line]");
    expect(line!.dataset.defaultKind).toBe("single");
    expect(within(clone).queryByRole("button", { name: SET_DEFAULT })).toBeNull();
    expect(within(clone).queryByText(TTS_DEFAULT)).toBeNull();
  });
});
