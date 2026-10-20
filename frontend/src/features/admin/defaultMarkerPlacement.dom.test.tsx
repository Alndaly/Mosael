/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「当前默认」这枚标记的**位置与形态**(维护者定的):它是**名字右边的一枚 badge**,
 * 不是右边状态槽里和「已安装」并排的第二件状态。
 *
 * 为什么分家:右边那一格回答的是「这一项现在能不能用」(已安装 / 可用 / 下载),而
 * 「当前默认」回答的是「这几项里选中的是它」。两件事并排放在同一格,读起来像一类 ——
 * 维护者原话:「这种当前默认的提示请你放在左侧 title 的右边,可以做成一个 badge 的样式」。
 *
 * 三处同一条规则(同一个 AdminDefaultMarker):转写模型、克隆引擎、降噪引擎。
 * 钉住四件事:
 *   1. DOM 顺序:标题 → badge → 说明;badge 在标题那一行里,不在右边控件 / 状态格;
 *   2. 右边只剩状态:那一格不出现「当前默认」;
 *   3. 形态:小圆角 + 浅底 + 小字的文字 badge(基础件 Badge 的 secondary 一档),不是一颗星;
 *   4. badge 的文字就是「当前默认」,没有原生 title。
 */

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  return {
    useI18n: () => (key: string) => (zhCN as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const CURRENT_DEFAULT = "当前默认";
const INSTALLED = "已安装";
const READY = "可用";

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

const denoiseEngine = (over: Record<string, unknown> = {}) => ({
  engine: "builtin:deepfilternet", label: "DeepFilterNet", description: "效果最好",
  installable: false, status: "ready", ready: true, removes_music: false, setup_hint: "",
  message: "", size_bytes: 0, strengths: [], is_default: false,
  ...over,
});

let asrModels: Array<Record<string, unknown>> = [];
let ttsModels: Array<Record<string, unknown>> = [];
let ttsConfig: Record<string, unknown> = {};
let denoiseEngines: Array<Record<string, unknown>> = [];

vi.mock("@/api/client", () => ({
  listAsrModels: () => Promise.resolve(asrModels),
  downloadAsrModel: (id: string) => Promise.resolve(asrModels.find((one) => one.id === id)),
  setDefaultAsrModel: (id: string) => Promise.resolve(asrModels.find((one) => one.id === id)),
  getTtsConfig: () => Promise.resolve(ttsConfig),
  updateTtsConfig: (body: Record<string, unknown>) => Promise.resolve({ ...ttsConfig, ...body }),
  listTtsModels: () => Promise.resolve(ttsModels),
  downloadTtsModel: (id: string) => Promise.resolve(ttsModels.find((one) => one.id === id)),
  listDenoiseEngines: () => Promise.resolve(denoiseEngines),
  installDenoiseEngine: () => Promise.resolve(denoiseEngines[0]),
  setDefaultDenoiseEngine: () => Promise.resolve(denoiseEngines[0]),
}));

import { AsrModelsSection } from "./AsrModelsSection";
import { DenoiseEnginesSection } from "./DenoiseEnginesSection";
import { VoiceCloneSection } from "./VoiceCloneSection";

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function section(id: string): HTMLElement {
  const node = document.querySelector(`[data-admin-section="${id}"]`);
  if (!(node instanceof HTMLElement)) throw new Error(`没有 ${id} 这一节`);
  return node;
}

/** 一条实现自己那一行 —— 默认行里也有同名文字(下拉的当前值),先把它排除掉。 */
function rowOf(scope: HTMLElement, label: string): HTMLElement {
  const row = [...scope.querySelectorAll<HTMLElement>("[data-admin-row]")]
    .filter((one) => one.closest("[data-admin-default-line]") === null)
    .find((one) => within(one).queryByText(label, { exact: true }));
  if (!row) throw new Error(`没有「${label}」那一行`);
  return row;
}

/**
 * 一行里的四件事都在这儿钉住:badge 在标题那一行、在标题之后、在说明之前,
 * 且**不在**右边那一格;文字是「当前默认」,形态是文字 badge(小圆角 / 浅底 / 小字)。
 */
function expectTitleBadge(row: HTMLElement, label: string) {
  const textCell = row.children[0] as HTMLElement;
  const titleLine = textCell.firstElementChild as HTMLElement;
  const title = within(titleLine).getByText(label, { exact: true });
  const description = row.querySelector<HTMLElement>("[data-admin-row-description]");
  const marker = row.querySelector<HTMLElement>("[data-admin-default-marker]");
  const control = row.querySelector<HTMLElement>("[data-admin-row-control]");

  expect(marker, "这一行没有「当前默认」").not.toBeNull();
  expect(description, "这一行没有说明").not.toBeNull();
  expect(control, "这一行没有右边那一格").not.toBeNull();

  //: 位置:和标题同一个盒子,在标题之后、说明之前。
  expect(titleLine.contains(marker), "badge 不在标题那一行里").toBe(true);
  expect(titleLine.contains(description), "说明不在标题那一行里").toBe(false);
  expect(title.compareDocumentPosition(marker!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(marker!.compareDocumentPosition(description!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  //: 分家:右边那一格没有它。
  expect(control!.contains(marker!), "badge 还在右边状态槽里").toBe(false);
  expect(control!.querySelector("[data-admin-default-marker]")).toBeNull();
  expect(within(control!).queryByText(CURRENT_DEFAULT)).toBeNull();

  //: 形态:文字 badge(小圆角 + 浅底 + 小字),不是原来的「星 + 一行小字」。
  expect(marker!.textContent?.trim()).toBe(CURRENT_DEFAULT);
  expect(marker).toHaveClass("rounded-md");
  expect(marker).toHaveClass("bg-secondary");
  expect(marker).toHaveClass("text-ui-xs");
  expect(marker).not.toHaveClass("rounded-full");
  //: 名称就是文字本身:没有原生 title,也没有只挂一颗星。
  expect(marker!.hasAttribute("title")).toBe(false);
  expect(marker!.querySelector("[title]")).toBeNull();
}

beforeEach(() => {
  asrModels = [
    asrModel({ id: "funasr", label: "FunASR", is_default: true }),
    asrModel({ id: "whisperx", engine: "whisperx", label: "WhisperX Large v3" }),
  ];
  ttsModels = [
    ttsEngine({ id: "f5-tts", label: "F5-TTS" }),
    ttsEngine({ id: "fish-speech", label: "Fish Speech" }),
  ];
  ttsConfig = {
    engine: "f5-tts", python_path: "", fish_repo_dir: "", fish_model_dir: "",
    worker_ready: true, worker_python: "/x/python", worker_checked: true,
  };
  denoiseEngines = [
    denoiseEngine({ is_default: true }),
    denoiseEngine({ engine: "builtin:rnnoise", label: "RNNoise" }),
  ];
});

describe("当前默认摆在哪:三处都是标题右边的一枚 badge", () => {
  it("转写模型:badge 在模型名之后、说明之前,不在右边状态槽", async () => {
    renderWithClient(<AsrModelsSection />);
    //: 节顶那个下拉的当前值也写着 FunASR —— 等列表行出来,不是等这一个字符串。
    await screen.findAllByText("FunASR");
    expectTitleBadge(rowOf(section("engine-transcribe"), "FunASR"), "FunASR");
    expect(within(rowOf(section("engine-transcribe"), "WhisperX Large v3")).queryByText(CURRENT_DEFAULT)).toBeNull();
  });

  it("克隆引擎:badge 在引擎名之后、说明之前,不在右边状态槽", async () => {
    renderWithClient(<VoiceCloneSection />);
    await screen.findByRole("heading", { name: "克隆引擎" });
    const clone = section("engine-clone");
    expectTitleBadge(rowOf(clone, "F5-TTS"), "F5-TTS");
    expect(within(rowOf(clone, "Fish Speech")).queryByText(CURRENT_DEFAULT)).toBeNull();
  });

  it("降噪:badge 在引擎名之后、说明之前,不在右边状态槽", async () => {
    renderWithClient(<DenoiseEnginesSection />);
    await screen.findAllByText("DeepFilterNet");
    const box = section("engine-denoise");
    expectTitleBadge(rowOf(box, "DeepFilterNet"), "DeepFilterNet");
    expect(within(rowOf(box, "RNNoise")).queryByText(CURRENT_DEFAULT)).toBeNull();
  });
});

describe("状态与徽标分家:右边只剩状态", () => {
  it("三处右边那一格只有「已安装 / 可用」,「当前默认」只在名字旁", async () => {
    renderWithClient(
      <>
        <AsrModelsSection />
        <VoiceCloneSection />
        <DenoiseEnginesSection />
      </>,
    );
    await screen.findAllByText("FunASR");
    await screen.findByRole("heading", { name: "克隆引擎" });
    await screen.findAllByText("F5-TTS");
    await screen.findAllByText("DeepFilterNet");

    const cases: Array<[string, string, string]> = [
      ["engine-transcribe", "FunASR", INSTALLED],
      ["engine-clone", "F5-TTS", INSTALLED],
      ["engine-denoise", "DeepFilterNet", READY],
    ];
    for (const [id, label, state] of cases) {
      const control = rowOf(section(id), label).querySelector<HTMLElement>("[data-admin-row-control]");
      expect(control, `${label} 没有右边那一格`).not.toBeNull();
      expect(control!.textContent?.trim()).toBe(state);
      expect(control!.querySelector("[data-admin-default-marker]")).toBeNull();
    }
  });
});
