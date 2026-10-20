/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「语音合成引擎」这一节的保存按钮,以及**改了默认之后表单里的 engine**。
 *
 * 两件事:
 *
 * 1. **保存和「改了还没保存」得装在一行里。** 此前保存飘在节头,不属于任何一行 ——
 *    读的人先得猜到它存的是下面那张表单;那一小句「改了还没保存」也跟着飘在节头。
 *    现在和「FFmpeg 路径」同一套行语法:「TTS 解释器」这一行的左格是标题 + 说明,
 *    右格是输入框 + 保存,未保存时的提示也贴在这一格里。保存是这张 `<form>` 的提交键
 *    (`type="submit"`;HTML 默认就是 submit,基础件把它改成了 button —— 见 design/buttonTypes)。
 *
 * 2. **设完默认,表单里的 `engine` 必须立刻跟上。** 默认就是 `TtsConfig.engine` 一个字段,
 *    它唯一的写入口是克隆组顶上那个下拉,选中即存。但表单里也带着一份 `engine`(保存时原样
 *    发回去,后端无条件覆盖四个键)。不跟上的话:用户先在下拉里把默认改成 Fish Speech,
 *    紧接着点「保存」—— 那一瞬间表单里还是旧 engine,PUT 把它写回去,刚设的默认被悄悄改回。
 *    「回读回来再 reset」不够:回读是另一次请求,而用户点保存不必等它。这条用例把回读**拖住**,
 *    钉的正是「回读还没回来就点保存」这一刻。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const toastError = vi.fn();
const toastSuccess = vi.fn();
//: 工厂会被提到文件顶上执行,所以这里只能放闭包 —— 直接写 `error: toastError` 会在 const 初始化前读它。
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}));

const base = {
  detail: "d", status: "installed", runtime_ready: true, runtime_checked: true,
  downloaded_bytes: 0, total_bytes: 0, expected_bytes: 1_000_000_000, total_is_estimate: true,
  speed_bps: 0, eta_seconds: null, message: "已安装", needs_source: false, source_ready: false,
  source_dir: "", sources: ["hf"], supports_speed: false,
};
//: 两个克隆引擎都装好,默认下拉里的两项才都能选(没装的会被禁用)。
const models = [
  { ...base, id: "f5-tts", label: "F5-TTS" },
  { ...base, id: "fish-speech", label: "Fish Speech" },
];

const INITIAL_CONFIG = {
  engine: "f5-tts", python_path: "", pip_index: "", fish_repo_dir: "", fish_model_dir: "",
  worker_ready: true, worker_python: "/x/python", worker_checked: true,
};
const config = { ...INITIAL_CONFIG };

/** 配置回读:默认马上答;某条用例把它挂住,钉「回读还没回来时点保存」。 */
let configRead: () => Promise<typeof config>;
/** 写接口失败时用。 */
let updateError: Error | null = null;
const updateTtsConfig = vi.fn((body: Record<string, unknown>) => {
  if (updateError) return Promise.reject(updateError);
  Object.assign(config, body);
  // 后端存下来了:再问一次就是这份(这里给一份新的对象,和真接口一样)。
  return Promise.resolve({ ...config });
});

vi.mock("@/api/client", () => ({
  getTtsConfig: () => configRead(),
  updateTtsConfig: (body: Record<string, unknown>) => updateTtsConfig(body),
  listTtsModels: () => Promise.resolve(models),
  downloadTtsModel: () => Promise.resolve(models[0]),
}));

import { VoiceCloneSection } from "./VoiceCloneSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VoiceCloneSection />
    </QueryClientProvider>,
  );
}

/** 「TTS 解释器」那一整行 —— 从输入框往上找最近的 AdminRow。 */
function interpreterRow(): HTMLElement {
  const input = screen.getByPlaceholderText("/path/to/venv/bin/python");
  const row = input.closest<HTMLElement>("[data-admin-row]");
  if (!row) throw new Error("「TTS 解释器」的输入框不在一个 [data-admin-row] 里");
  return row;
}

function interpreterControl(): HTMLElement {
  const control = interpreterRow().querySelector<HTMLElement>("[data-admin-row-control]");
  if (!control) throw new Error("「TTS 解释器」那一行没有控件格");
  return control;
}

/** 这一节的节头(标题 + 说明 + 动作)。 */
function sectionHeader(container: HTMLElement): HTMLElement {
  const header = container.querySelector<HTMLElement>('[data-admin-section="engine-clone"] > header');
  if (!header) throw new Error("「语音合成引擎」没有节头");
  return header;
}

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

beforeEach(() => {
  Object.assign(config, INITIAL_CONFIG);
  updateTtsConfig.mockClear();
  toastError.mockClear();
  toastSuccess.mockClear();
  updateError = null;
  configRead = () => Promise.resolve({ ...config });
});

describe("保存按钮和「改了还没保存」在「TTS 解释器」那一行里", () => {
  it("保存按钮在那一行的控件格里,不在节头", async () => {
    const { container } = renderSection();
    await screen.findByPlaceholderText("/path/to/venv/bin/python");

    const save = screen.getByRole("button", { name: "save" });
    expect(interpreterControl().contains(save), "保存按钮属于「TTS 解释器」那一行的控件格").toBe(true);
    const header = sectionHeader(container);
    expect(header.contains(save), "节头不该再挂一颗保存").toBe(false);
    expect(within(header).queryByRole("button", { name: "save" })).toBeNull();
  });

  it("整节只有一颗保存,而且是这张表单的提交键", async () => {
    renderSection();
    await screen.findByPlaceholderText("/path/to/venv/bin/python");

    const saves = screen.getAllByRole("button", { name: "save" });
    expect(saves).toHaveLength(1);
    expect(saves[0]).toHaveAttribute("type", "submit");
    expect(saves[0].closest("form"), "提交键得在一张 form 里").not.toBeNull();
  });

  it("「改了还没保存」也在那一行的控件格里,不在节头", async () => {
    const { container } = renderSection();
    const input = await screen.findByPlaceholderText("/path/to/venv/bin/python");
    await userEvent.type(input, "/tmp/py");

    const note = await screen.findByText(/ttsSaveAndDownload/);
    expect(interpreterControl().contains(note), "未保存的提示贴在这一行的控件格").toBe(true);
    expect(sectionHeader(container).contains(note)).toBe(false);
  });
});

describe("先改默认、再点保存:刚设的默认不会被改回去", () => {
  it("设完默认之后,保存发出的 engine 就是新的默认", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByPlaceholderText("/path/to/venv/bin/python");
    const trigger = await screen.findByRole("combobox", { name: "voiceCloneEngine" });

    //: 回读挂住 —— 设完默认之后那一问迟迟不回,用户这时就点了保存。
    configRead = () => new Promise<never>(() => {});

    await user.click(trigger);
    await user.click(await screen.findByRole("option", { name: "Fish Speech" }));
    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalledTimes(1));
    //: 默认仍是「选中即存」:选完就写,不必再点保存。
    expect(updateTtsConfig.mock.calls[0][0]).toMatchObject({ engine: "fish-speech" });

    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalledTimes(2));
    //: **这一条就是那个潜在 bug**:不跟上的话这里是 "f5-tts",默认被悄悄改回。
    expect(updateTtsConfig.mock.calls[1][0]).toMatchObject({ engine: "fish-speech" });
  });
});

describe("回归:载荷、失败提示、选中即存", () => {
  it("保存的载荷仍是四个键 —— fish 的两项不能被漏发(漏了就是清空)", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByPlaceholderText("/path/to/venv/bin/python");

    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalled());
    expect(Object.keys(updateTtsConfig.mock.calls[0][0]).sort()).toEqual([
      "engine", "fish_model_dir", "fish_repo_dir", "python_path",
    ]);
  });

  it("F5 / Fish 的默认仍是「选中即存」—— 选完就写,不必再点保存", async () => {
    const user = userEvent.setup();
    renderSection();
    const trigger = await screen.findByRole("combobox", { name: "voiceCloneEngine" });

    await user.click(trigger);
    await user.click(await screen.findByRole("option", { name: "Fish Speech" }));
    await waitFor(() => expect(updateTtsConfig).toHaveBeenCalledTimes(1));
    expect(updateTtsConfig.mock.calls[0][0]).toMatchObject({ engine: "fish-speech" });
  });

  it("保存失败仍是 toast:不在这节里另起一张行内错误卡", async () => {
    const user = userEvent.setup();
    updateError = new Error("存不进去");
    const { container } = renderSection();
    await screen.findByPlaceholderText("/path/to/venv/bin/python");

    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("存不进去"));
    expect(screen.queryByText("存不进去")).toBeNull();
    expect(container.querySelector("[data-failure]")).toBeNull();
  });
});
