/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 这一节管的是**本机跑**的引擎:随应用带着的、要用户点下载的。**云端引擎(Edge TTS)不是一行**
 * —— 它不在本机跑、也没有权重,入口在剪辑台的「配音」或创作页「语音」的引擎下拉里。
 *
 * 这里钉三件事:节标题与说明真的渲染出来(不是只改了文案表);表里没有 Edge 那一行 ——
 * 行只来自 `/api/tts/models` 的本机引擎目录,谁日后往表里硬塞一行 Edge 都会被这条抓住;
 * 以及现有的引擎行与默认下拉没被这次改文案碰到。
 */

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

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  return {
    useI18n: () => (key: string) => (zhCN as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("@/api/client", () => ({
  getTtsConfig: () => Promise.resolve(config),
  updateTtsConfig: () => Promise.resolve(config),
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

function section(): HTMLElement {
  const node = document.querySelector<HTMLElement>('[data-admin-section="engine-clone"]');
  if (!node) throw new Error("没有「本地语音合成引擎」这一节");
  return node;
}

/** 表里的行(下载/状态那一套),不含组头上的「默认」那一行。 */
function engineRows(): HTMLElement[] {
  return [...section().querySelectorAll<HTMLElement>("[data-engine-group] [data-admin-row]")].filter(
    (row) => row.closest("[data-admin-default-line]") === null,
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

describe("「本地语音合成引擎」这一节", () => {
  it("标题渲染成「本地语音合成引擎」", async () => {
    renderSection();
    expect(await screen.findByRole("heading", { level: 2, name: "本地语音合成引擎" })).toBeInTheDocument();
  });

  it("说明里说清本机跑、两种来源,以及云端引擎不在这里", async () => {
    renderSection();
    const desc = await screen.findByText(/这里管的是本机跑的语音引擎/);
    expect(desc.textContent).toContain("随应用带着");
    expect(desc.textContent).toContain("要下权重");
    expect(desc.textContent).toContain("云端引擎");
    expect(desc.textContent).toContain("不在这里");
  });

  it("那张表里没有 Edge 行 —— 云端引擎不该混进来", async () => {
    renderSection();
    await screen.findByRole("heading", { name: "克隆引擎" });
    //: 只在**表**里找:节说明里那句「云端引擎(如 Edge)不在这里」是说明,不是一行。
    for (const group of section().querySelectorAll<HTMLElement>("[data-engine-group]")) {
      expect(within(group).queryByText(/edge/i)).toBeNull();
    }
    //: 行只有 API 给的三个本机引擎;多一行就会在这里露出来。
    expect(engineRows()).toHaveLength(3);
  });

  it("现有引擎行没变:F5 / Fish 在克隆组,Qwen3-TTS 在预置音色组", async () => {
    renderSection();
    await screen.findByRole("heading", { name: "克隆引擎" });

    const text = engineRows().map((row) => row.textContent ?? "");
    expect(text.some((one) => one.includes("F5-TTS"))).toBe(true);
    expect(text.some((one) => one.includes("Fish Speech S2 Pro"))).toBe(true);
    expect(text.some((one) => one.includes("Qwen3-TTS"))).toBe(true);
  });

  it("默认下拉没变:还是「默认克隆引擎」,默认 F5-TTS", async () => {
    renderSection();
    await screen.findByRole("heading", { name: "克隆引擎" });

    const trigger = within(section()).getByRole("combobox", { name: "默认克隆引擎" });
    expect(trigger).toHaveTextContent("F5-TTS");
  });
});
