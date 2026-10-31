/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 管理 → 引擎 →「语音合成引擎」:那张**可下载权重**的表按能力分两区。
 *
 * 这一节此前整节都叫「声音克隆」,表里却同时列着 Qwen3-TTS —— 一个自己写着「不克隆、不要参考
 * 音频」的预置音色引擎。标题、说明、下拉都在说"克隆",于是它被读成克隆引擎;用户装好后回到
 * 这一节,下拉里只有 F5/Fish,就以为"装了却选不到它"。
 *
 * 分组只改**渲染**:下载、状态、进度、失败、重试仍然是同一份 ModelDownloadRow 和同一个
 * download mutation。这里钉住两组组头、行归属、Qwen 那行的指路,以及默认在克隆组里用行内
 * 「设为默认」、不再是一个只列两家的下拉。
 */

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  return {
    useI18n: () => (key: string) => (zhCN as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});

const base = {
  detail: "d", status: "missing", runtime_ready: false, runtime_checked: true, downloaded_bytes: 0,
  total_bytes: 0, expected_bytes: 1_000_000_000, total_is_estimate: true, speed_bps: 0,
  eta_seconds: null, message: "未下载", needs_source: false, source_ready: false, source_dir: "",
  sources: ["hf"], speed_control: "stretch",
};
const models = [
  { ...base, id: "f5-tts", label: "F5-TTS" },
  { ...base, id: "fish-speech", label: "Fish Speech S2 Pro" },
  { ...base, id: "qwen-tts", label: "Qwen3-TTS" },
];
//: 每条用例从同一份「什么都没装」起步 —— 有的用例要把两行改成已安装,不能漏给下一条。
const INITIAL_MODELS = models.map((one) => ({ ...one }));
beforeEach(() => {
  models.splice(0, models.length, ...INITIAL_MODELS.map((one) => ({ ...one })));
});
const config = {
  engine: "f5-tts",
  python_path: "",
  pip_index: "",
  fish_repo_dir: "",
  fish_model_dir: "",
  worker_ready: true,
  worker_python: "/x/python",
  worker_checked: true,
};

const downloadTtsModel = vi.fn((_id: string) => Promise.resolve(models[0]));
vi.mock("@/api/client", () => ({
  getTtsConfig: () => Promise.resolve(config),
  updateTtsConfig: () => Promise.resolve(config),
  listTtsModels: () => Promise.resolve(models),
  downloadTtsModel: (id: string) => downloadTtsModel(id),
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

function group(kind: "clone" | "preset"): HTMLElement {
  const node = document.querySelector(`[data-engine-group="${kind}"]`);
  if (!(node instanceof HTMLElement)) throw new Error(`没有 ${kind} 这一组`);
  return node;
}

/** 等两组都渲染出来 —— 引擎列表是异步取的,表单先出来不代表行已经到了。 */
async function waitForGroups(): Promise<void> {
  await screen.findByRole("heading", { name: "克隆引擎" });
  await screen.findByRole("heading", { name: "预置音色引擎" });
}

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

describe("语音合成引擎这一节", () => {
  it("标题从「声音克隆」改成「本地语音合成引擎」", async () => {
    renderSection();
    expect(await screen.findByRole("heading", { level: 2, name: "本地语音合成引擎" })).toBeInTheDocument();
  });

  it("按能力分两组:克隆引擎一组、预置音色引擎一组", async () => {
    renderSection();
    await waitForGroups();

    expect(within(group("clone")).getByRole("heading", { name: "克隆引擎" })).toBeInTheDocument();
    expect(within(group("preset")).getByRole("heading", { name: "预置音色引擎" })).toBeInTheDocument();
    // 组头下面那句不是空的 —— 两个组各讲自己的合成方式。
    expect(within(group("clone")).getByText(/参考音频/)).toBeInTheDocument();
    expect(within(group("preset")).getByText(/不克隆/)).toBeInTheDocument();
  });

  it("F5 / Fish 在第一组,Qwen3-TTS 在第二组", async () => {
    renderSection();
    await waitForGroups();

    //: 克隆组顶上的「默认克隆引擎」也会写着默认的那个名字,所以这里按出现次数断言归属。
    expect(within(group("clone")).getAllByText("F5-TTS").length).toBeGreaterThan(0);
    expect(within(group("clone")).getAllByText("Fish Speech S2 Pro").length).toBeGreaterThan(0);
    expect(within(group("clone")).queryByText("Qwen3-TTS")).toBeNull();

    expect(within(group("preset")).getByText("Qwen3-TTS")).toBeInTheDocument();
    expect(within(group("preset")).queryByText("F5-TTS")).toBeNull();
  });

  it("Qwen 那行说清不在这里切换,并指向真实存在的「配音」和「语音」", async () => {
    renderSection();
    const qwen = await screen.findByText("Qwen3-TTS");

    const preset = group("preset");
    const hint = within(preset).getByText((content, element) =>
      element?.tagName === "P" && content.includes("不在这里切换"));
    expect(hint.textContent).toContain("配音");
    expect(hint.textContent).toContain("语音");
    // 指路那句紧跟在 Qwen 自己那一行里,不是飘在整节的说明里。
    expect(preset.textContent).toContain(qwen.textContent);
    expect(preset.textContent).toContain("剪辑台");
  });

  it("下载/状态仍然是同一套:每行都还是那个下载按钮,点了还是调同一个接口", async () => {
    renderSection();
    await waitForGroups();

    const buttons = within(group("clone")).getAllByRole("button", { name: /下载/ });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[0]);
    await waitFor(() => expect(downloadTtsModel).toHaveBeenCalledWith("f5-tts"));
  });

  it("默认是一个下拉(在克隆组说明之后);列表行没有「设为默认」,已默认那行只有淡标记", async () => {
    //: 两行都装好才谈得上"选谁"。
    models[0] = { ...models[0], status: "installed", runtime_ready: true };
    models[1] = { ...models[1], status: "installed", runtime_ready: true };
    renderSection();
    await waitForGroups();

    //: 下拉在克隆组里,而且整组只有这一个能改默认。
    const clone = group("clone");
    const trigger = within(clone).getByRole("combobox", { name: "默认克隆引擎" });
    expect(trigger).toHaveTextContent("F5-TTS");
    expect(within(clone).getAllByRole("combobox")).toHaveLength(1);

    //: 默认那一行现在也是 AdminRow(整行),触发器里同样写着 F5-TTS —— 只找列表里的行。
    const rows = [...clone.querySelectorAll<HTMLElement>("[data-admin-row]")].filter(
      (row) => row.closest("[data-admin-default-line]") === null,
    );
    const f5 = rows.find((row) => row.textContent?.includes("F5-TTS"))!;
    const fish = rows.find((row) => row.textContent?.includes("Fish Speech S2 Pro"))!;
    //: 已默认 = 一枚不可点的「当前默认」,不是「设为默认」按钮,也不是可点的状态。
    const marker = f5.querySelector<HTMLElement>("[data-admin-default-marker]");
    expect(marker).toHaveTextContent("当前默认");
    expect(marker!.closest("button")).toBeNull();
    expect(within(fish).queryByRole("button", { name: "设为默认" })).toBeNull();
    expect(fish.querySelector("[data-admin-default-marker]")).toBeNull();
    //: Qwen3-TTS 是预置音色引擎,不属于"默认克隆引擎";后端 PUT 也只收 f5-tts|fish-speech。
    expect(within(group("preset")).queryByText("当前默认")).toBeNull();
  });

  it("没安装的克隆引擎选项禁用,并写着为什么", async () => {
    //: 两行都没装 —— 下载/状态照旧,选择器里两项都点不了,但理由看得见。
    renderSection();
    await waitForGroups();

    await userEvent.click(within(group("clone")).getByRole("combobox", { name: "默认克隆引擎" }));
    const fish = await screen.findByRole("option", { name: /Fish Speech S2 Pro/ });
    expect(fish).toHaveAttribute("aria-disabled", "true");
    expect(fish).toHaveTextContent("还没安装,先下载");
    expect(screen.getByRole("option", { name: "F5-TTS" })).toHaveAttribute("aria-disabled", "true");
  });
});
