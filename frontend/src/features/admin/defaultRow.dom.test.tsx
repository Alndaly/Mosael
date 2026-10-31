/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { zhCN } from "@/app/messages/zh-CN";

/**
 * 「默认」的摆放规则(维护者定的):**只出现在同一能力有多个可选实现的地方**,并且永远放在
 * 这些实现所在的那一节里 —— 节说明之后、实现列表之前。
 *
 * 这一组钉住五个决定:
 *   1. 那句话/那个控件由**数据**决定:≥2 个候选才有选择器,只有 1 个则说清"没有默认可设",
 *      数据没到(undefined)就什么都不画 —— 别把"未知"画成"只有一个";
 *   2. 位置统一:默认永远在说明之后、列表之前(转写是节说明之后;TTS 是克隆组说明之后);
 *   3. 交互统一:ASR 和 TTS 都是**一个下拉**,那是整节唯一能改默认的地方;
 *   4. 列表行不再承担"设默认":行里没有「设为默认」按钮,已默认那行只剩一枚不可点的淡标记;
 *   5. 未安装的选项在下拉里禁用,并给出理由("还没安装,先下载")。
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
  source_ready: false, source_dir: "", sources: ["hf"], speed_control: "stretch",
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
const setDefaultAsrModel = vi.fn();
//: 数据"还没到":接口一直不答。用来钉「undefined 不画控件」。
let holdAsr = false;
let holdTtsConfig = false;
let holdTtsModels = false;

//: 「模型下载源」那一行(InstallSourceSection)也在这条测试里渲染 —— 默认行要和它是同一张卡片。
const installSource = {
  pip_index: "", npm_registry: "", pip_presets: [], npm_presets: [],
  pytorch_index: "", pytorch_presets: [], github_mirror: "",
  model_source: "hf-mirror", model_sources: ["hf-mirror", "hf", "modelscope"],
};

vi.mock("@/api/client", () => ({
  getInstallSource: () => Promise.resolve(installSource),
  updateInstallSource: (body: Record<string, unknown>) => Promise.resolve({ ...installSource, ...body }),
  listAsrModels: () => (holdAsr ? new Promise<never>(() => {}) : Promise.resolve(asrModels)),
  downloadAsrModel: (id: string) => Promise.resolve(asrModels.find((one) => one.id === id)),
  setDefaultAsrModel: (id: string) => {
    setDefaultAsrModel(id);
    asrModels = asrModels.map((one) => ({ ...one, is_default: one.id === id }));
    return Promise.resolve(asrModels.find((one) => one.id === id));
  },
  getTtsConfig: () => (holdTtsConfig ? new Promise<never>(() => {}) : Promise.resolve(ttsConfig)),
  updateTtsConfig: (body: Record<string, unknown>) => {
    updateTtsConfig(body);
    // 后端真的存下来了:再问一次配置时,新答案就是它。
    ttsConfig = { ...ttsConfig, ...body };
    return Promise.resolve(ttsConfig);
  },
  listTtsModels: () => (holdTtsModels ? new Promise<never>(() => {}) : Promise.resolve(ttsModels)),
  downloadTtsModel: (id: string) => Promise.resolve(ttsModels.find((one) => one.id === id)),
  listSeparationEngines: () => Promise.resolve(separationEngines),
  installSeparationEngine: () => Promise.resolve(separationEngines[0]),
}));

import { AsrModelsSection } from "./AsrModelsSection";
import { InstallSourceSection } from "./InstallSourceSection";
import { SeparationEnginesSection } from "./SeparationEnginesSection";
import { VoiceCloneSection } from "./VoiceCloneSection";
import { ADMIN_CARD } from "./adminLayout";

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
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

/** 一条实现(一个引擎/模型)自己那一行 —— 控件里也会出现引擎名,所以不能只按文字找。
 *  默认那一行现在也是 AdminRow(整行),它的下拉里同样写着引擎名,得先把那一行排除掉。 */
function rowByLabel(scope: HTMLElement, label: string): HTMLElement {
  const row = [...scope.querySelectorAll<HTMLElement>("[data-admin-row]")]
    .filter((one) => one.closest("[data-admin-default-line]") === null)
    .find((one) => within(one).queryByText(label));
  if (!row) throw new Error(`没有「${label}」那一行`);
  return row;
}

/** 默认那一行(控件 / 只有一句话时的那句)。 */
function defaultLine(scope: HTMLElement): HTMLElement {
  const line = scope.querySelector<HTMLElement>("[data-admin-default-line]");
  if (!line) throw new Error("没有默认那一行");
  return line;
}

const DEFAULT_ONLY_ONE = "这一节只有一种引擎,所以没有默认可设。";
const CURRENT_DEFAULT = "当前默认";
const NOT_INSTALLED_REASON = "还没安装,先下载";
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
  setDefaultAsrModel.mockClear();
  holdAsr = false;
  holdTtsConfig = false;
  holdTtsModels = false;
});

describe("转写模型:默认是说明之后、列表之前的一个下拉", () => {
  it("多个模型 → 下拉在节说明之后、模型列表之前,当前值就是默认模型", async () => {
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const box = section("engine-transcribe");
    const line = defaultLine(box);
    expect(line.dataset.defaultKind).toBe("choice");
    expect(line).toHaveTextContent(ASR_DEFAULT);

    const trigger = within(line).getByRole("combobox", { name: ASR_DEFAULT });
    // 触发器里是**当前值**,不是一个只读的「默认是哪个」。
    expect(trigger).toHaveTextContent("FunASR");

    // 节说明(header)之后、模型列表那一张卡之前。
    expect(line.previousElementSibling).toBe(box.querySelector("header"));
    const card = line.nextElementSibling as HTMLElement;
    expect(card.querySelector("[data-admin-row]")).not.toBeNull();
  });

  it("整节只有这一个能改默认的控件;列表行没有「设为默认」,已默认那行只有淡标记", async () => {
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const box = section("engine-transcribe");
    // 唯一可写处:一个下拉。列表行里再没有第二颗「设为默认」。
    expect(within(box).getAllByRole("combobox")).toHaveLength(1);
    expect(within(box).queryByRole("button", { name: "设为默认" })).toBeNull();

    const funasr = rowByLabel(box, "FunASR");
    const marker = funasr.querySelector<HTMLElement>("[data-admin-default-marker]");
    expect(marker).not.toBeNull();
    expect(marker).toHaveTextContent(CURRENT_DEFAULT);
    // 只是字:不是按钮、也点不动。
    expect(marker!.closest("button")).toBeNull();
    expect(within(funasr).queryByRole("button", { name: CURRENT_DEFAULT })).toBeNull();
    // 另一行没有这枚标记。
    expect(rowByLabel(box, "WhisperX").querySelector("[data-admin-default-marker]")).toBeNull();
  });

  it("在下拉里选另一个装好的模型 → 写默认、列表重新读一次,标记跟着过去", async () => {
    const user = userEvent.setup();
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const box = section("engine-transcribe");
    await user.click(within(box).getByRole("combobox", { name: ASR_DEFAULT }));
    await user.click(await screen.findByRole("option", { name: "WhisperX" }));

    await waitFor(() => expect(setDefaultAsrModel).toHaveBeenCalledWith("whisperx"));
    await waitFor(() =>
      expect(within(section("engine-transcribe")).getByRole("combobox", { name: ASR_DEFAULT })).toHaveTextContent(
        "WhisperX",
      ),
    );
    await waitFor(() => {
      expect(rowByLabel(section("engine-transcribe"), "WhisperX").querySelector("[data-admin-default-marker]")).not.toBeNull();
      expect(rowByLabel(section("engine-transcribe"), "FunASR").querySelector("[data-admin-default-marker]")).toBeNull();
    });
    // 写完之后还是只有这一个能改。
    expect(within(section("engine-transcribe")).getAllByRole("combobox")).toHaveLength(1);
  });

  it("还没设过默认时触发器写「自动」,选一个装好的就设上", async () => {
    const user = userEvent.setup();
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR" }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const box = section("engine-transcribe");
    expect(within(box).getByRole("combobox", { name: ASR_DEFAULT })).toHaveTextContent("自动(还没设默认)");

    await user.click(within(box).getByRole("combobox", { name: ASR_DEFAULT }));
    await user.click(await screen.findByRole("option", { name: "FunASR" }));

    await waitFor(() => expect(setDefaultAsrModel).toHaveBeenCalledWith("funasr"));
    await waitFor(() =>
      expect(within(section("engine-transcribe")).getByRole("combobox", { name: ASR_DEFAULT })).toHaveTextContent(
        "FunASR",
      ),
    );
    expect(
      rowByLabel(section("engine-transcribe"), "FunASR").querySelector("[data-admin-default-marker]"),
    ).not.toBeNull();
  });

  it("未安装的模型在选项里禁用,并写着为什么", async () => {
    const user = userEvent.setup();
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX", status: "missing", runtime_ready: false }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    await user.click(within(section("engine-transcribe")).getByRole("combobox", { name: ASR_DEFAULT }));
    const missing = await screen.findByRole("option", { name: /WhisperX/ });
    expect(missing).toHaveAttribute("aria-disabled", "true");
    expect(missing).toHaveTextContent(NOT_INSTALLED_REASON);
    // 装好的那个仍然能选。
    expect(screen.getByRole("option", { name: "FunASR" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("只有一个模型 → 没有下拉,只说那一句", async () => {
    asrModels = [asrModel({ id: "funasr", label: "FunASR" })];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("FunASR");

    const box = section("engine-transcribe");
    const line = defaultLine(box);
    expect(line.dataset.defaultKind).toBe("single");
    expect(line).toHaveTextContent(DEFAULT_ONLY_ONE);
    //: 单实现也是整行:标题在左、那句话是行的说明,右边没有控件。
    const row = line.querySelector<HTMLElement>("[data-admin-row]");
    expect(row).not.toBeNull();
    expect(within(row!).getByText(ASR_DEFAULT)).toBeInTheDocument();
    expect(row!.querySelector("[data-admin-row-description]")).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(row!.querySelector("[data-admin-row-control]")).toBeNull();
    expect(within(box).queryByRole("combobox")).toBeNull();
    expect(within(box).queryByText(CURRENT_DEFAULT)).toBeNull();
  });

  it("数据还没到(undefined)时什么都不画 —— 未知不是「只有一个」", async () => {
    holdAsr = true;
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("正在连接后端");

    const box = section("engine-transcribe");
    expect(box.querySelector("[data-admin-default-line]")).toBeNull();
    expect(within(box).queryByRole("combobox")).toBeNull();
    expect(within(box).queryByText(DEFAULT_ONLY_ONE)).toBeNull();
  });
});

describe("默认那一行和「模型下载源」是同一种整行", () => {
  it("同一张卡片、同一个行:外层类与「模型下载源」那一行一模一样,行本身不描边", async () => {
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(
      <>
        <AsrModelsSection />
        <InstallSourceSection />
      </>,
    );
    await screen.findByText("WhisperX");

    //: 参照:「模型下载源」是卡片里的一行(AdminRow)。
    const sourcePicker = await screen.findByRole("combobox", { name: zhCN.voiceCloneSource });
    const sourceRow = sourcePicker.closest("[data-admin-row]") as HTMLElement;
    expect(sourceRow).not.toBeNull();
    const sourceCard = sourceRow.parentElement as HTMLElement;

    const line = defaultLine(section("engine-transcribe"));
    expect(line.className, "默认行外层就是那张卡片").toBe(sourceCard.className);
    expect(line.className).toBe(ADMIN_CARD);
    const row = line.querySelector<HTMLElement>("[data-admin-row]");
    expect(row, "默认行里就是那一种行").not.toBeNull();
    //: 卡片画边框和圆角,行本身不画 —— 参照那一行也是这样。
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("rounded-lg");
    expect(row!.className).toBe(sourceRow.className);
  });

  it("左边标题 + 说明、右边下拉;DOM 顺序就是标题 → 说明 → 控件", async () => {
    asrModels = [
      asrModel({ id: "funasr", label: "FunASR", is_default: true }),
      asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX" }),
    ];
    renderWithClient(<AsrModelsSection />);
    await screen.findByText("WhisperX");

    const line = defaultLine(section("engine-transcribe"));
    const row = line.querySelector<HTMLElement>("[data-admin-row]")!;
    const textCell = row.children[0] as HTMLElement;
    const controlCell = row.children[1] as HTMLElement;

    //: 左格:标题一行 + 说明一行。
    expect(within(textCell).getByText(ASR_DEFAULT)).toBeInTheDocument();
    const description = textCell.querySelector<HTMLElement>("[data-admin-row-description]");
    expect(description).toHaveTextContent(zhCN.defaultRowHint);
    //: 右格:那个下拉本身没变,仍是唯一能写默认的控件。
    expect(controlCell).toHaveAttribute("data-admin-row-control");
    expect(within(controlCell).getByRole("combobox", { name: ASR_DEFAULT })).toBeInTheDocument();
    //: 控件在文字之后,不是左边塞一个小 label、右边再放一个小下拉。
    expect(row.lastElementChild).toBe(controlCell);
    expect(textCell.compareDocumentPosition(controlCell) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("人声与背景音分离:只有一种引擎", () => {
  it("说清没有默认可设,而且那句话在说明之后、列表之前", async () => {
    separationEngines = [separationEngine()];
    renderWithClient(<SeparationEnginesSection />);
    await screen.findByText("Demucs");

    const box = section("engine-separation");
    const line = defaultLine(box);
    expect(line.dataset.defaultKind).toBe("single");
    expect(line).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(line.previousElementSibling).toBe(box.querySelector("header"));
    expect(line.nextElementSibling?.querySelector("[data-admin-row]")).not.toBeNull();
    expect(within(box).queryByRole("combobox")).toBeNull();
  });

  it("单实现也用整行:那句话在行的说明里,右边没有控件", async () => {
    separationEngines = [separationEngine()];
    renderWithClient(<SeparationEnginesSection />);
    await screen.findByText("Demucs");

    const line = defaultLine(section("engine-separation"));
    expect(line.className, "和别的行同一张卡片").toBe(ADMIN_CARD);
    const row = line.querySelector<HTMLElement>("[data-admin-row]");
    expect(row, "单实现也是整行,不是一行小字").not.toBeNull();
    expect(row!.querySelector("[data-admin-row-description]")).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(row!.querySelector("[data-admin-row-control]")).toBeNull();
    expect(within(line).queryByRole("combobox")).toBeNull();
  });
});

describe("语音合成引擎:默认是克隆组说明之后、列表之前的一个下拉", () => {
  beforeEach(() => {
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "fish-speech", label: "Fish Speech" }),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
  });

  it("克隆组:下拉在组说明之后、两行之前,当前值是已保存的默认", async () => {
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    const line = defaultLine(clone);
    expect(line.dataset.defaultKind).toBe("choice");
    expect(line).toHaveTextContent(TTS_DEFAULT);
    expect(within(line).getByRole("combobox", { name: TTS_DEFAULT })).toHaveTextContent("F5-TTS");
    // 组说明之后、克隆引擎列表之前。
    expect(line.previousElementSibling).toBe(clone.querySelector("h3")!.parentElement);
    expect(line.nextElementSibling?.querySelector("[data-admin-row]")).not.toBeNull();

    // 预置音色那一组只有一种引擎 —— 它没有选择器,只有那句话。
    const preset = group("preset");
    const note = defaultLine(preset);
    expect(note.dataset.defaultKind).toBe("single");
    expect(note).toHaveTextContent(DEFAULT_ONLY_ONE);
    expect(within(preset).queryByRole("combobox")).toBeNull();
  });

  it("列表行没有「设为默认」;已默认那行只有一枚不可点的「当前默认」", async () => {
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    expect(within(clone).getAllByRole("combobox")).toHaveLength(1);
    expect(within(clone).queryByRole("button", { name: "设为默认" })).toBeNull();

    const f5 = rowByLabel(clone, "F5-TTS");
    const marker = f5.querySelector<HTMLElement>("[data-admin-default-marker]");
    expect(marker).not.toBeNull();
    expect(marker).toHaveTextContent(CURRENT_DEFAULT);
    expect(marker!.closest("button")).toBeNull();
    expect(rowByLabel(clone, "Fish Speech").querySelector("[data-admin-default-marker]")).toBeNull();
    // 预置音色引擎不属于「默认克隆引擎」。
    expect(within(group("preset")).queryByText(CURRENT_DEFAULT)).toBeNull();
  });

  it("在下拉里换一个 → 写进 TtsConfig.engine —— 只有这一处可写", async () => {
    const user = userEvent.setup();
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    await user.click(within(group("clone")).getByRole("combobox", { name: TTS_DEFAULT }));
    await user.click(await screen.findByRole("option", { name: "Fish Speech" }));

    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalledTimes(1));
    expect(updateTtsConfig).toHaveBeenCalledWith(
      expect.objectContaining({ engine: "fish-speech", python_path: "" }),
    );

    await waitFor(() =>
      expect(within(group("clone")).getByRole("combobox", { name: TTS_DEFAULT })).toHaveTextContent("Fish Speech"),
    );
    await waitFor(() => {
      expect(rowByLabel(group("clone"), "Fish Speech").querySelector("[data-admin-default-marker]")).not.toBeNull();
      expect(rowByLabel(group("clone"), "F5-TTS").querySelector("[data-admin-default-marker]")).toBeNull();
    });
    expect(within(group("clone")).getAllByRole("combobox")).toHaveLength(1);
  });

  it("还没装的克隆引擎在选项里禁用,并写着为什么", async () => {
    const user = userEvent.setup();
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "fish-speech", label: "Fish Speech", status: "missing", runtime_ready: false }),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    await user.click(within(group("clone")).getByRole("combobox", { name: TTS_DEFAULT }));
    const fish = await screen.findByRole("option", { name: /Fish Speech/ });
    expect(fish).toHaveAttribute("aria-disabled", "true");
    expect(fish).toHaveTextContent(NOT_INSTALLED_REASON);
    expect(screen.getByRole("option", { name: "F5-TTS" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("克隆引擎只剩一种时也不摆选择器 —— 与「≥2 才有默认」同一条规则", async () => {
    ttsModels = [
      ttsEngine(),
      ttsEngine({ id: "qwen-tts", label: "Qwen3-TTS", status: "missing", runtime_ready: false }),
    ];
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    const line = defaultLine(clone);
    expect(line.dataset.defaultKind).toBe("single");
    expect(within(clone).queryByRole("combobox")).toBeNull();
    expect(within(clone).queryByText(CURRENT_DEFAULT)).toBeNull();
  });

  it("配置还没到(undefined)时什么都不画 —— 别把未知画成「只有一个」", async () => {
    holdTtsConfig = true;
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });

    const clone = group("clone");
    expect(clone.querySelector("[data-admin-default-line]")).toBeNull();
    expect(within(clone).queryByRole("combobox")).toBeNull();
    expect(within(clone).queryByText(DEFAULT_ONLY_ONE)).toBeNull();
  });

  it("权重表还没到(undefined)时也不画控件 / 不画那句话", async () => {
    holdTtsModels = true;
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "本地语音合成引擎" });

    const box = section("engine-clone");
    expect(box.querySelector("[data-admin-default-line]")).toBeNull();
    expect(within(box).queryByRole("combobox")).toBeNull();
    expect(within(box).queryByText(DEFAULT_ONLY_ONE)).toBeNull();
  });
});
