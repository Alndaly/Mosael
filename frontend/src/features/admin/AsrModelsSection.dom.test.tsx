/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 管理 → 引擎 → 转写:每个模型是卡片里的一行(和管理页其余的行同一套版式),而下载、进度、
 * 「已安装」、运行环境检测、失败重试照旧。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const base = {
  detail: "中文识别", status: "missing", runtime_ready: false, runtime_checked: true, downloaded_bytes: 0,
  total_bytes: 0, expected_bytes: 973_000_000, total_is_estimate: false, speed_bps: 0, eta_seconds: null, message: "",
};
let models: Array<Record<string, unknown>> = [];
const downloads: string[] = [];

vi.mock("@/api/client", () => ({
  listAsrModels: () => Promise.resolve(models),
  downloadAsrModel: (id: string) => {
    downloads.push(id);
    return Promise.resolve(models[0]);
  },
}));

import { AsrModelsSection } from "./AsrModelsSection";
import { ADMIN_CARD } from "./adminLayout";

function renderSection(rows: Array<Record<string, unknown>>) {
  models = rows;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AsrModelsSection />
    </QueryClientProvider>,
  );
}

const rowOf = async (label: string) =>
  (await screen.findByText(label)).closest("[data-admin-row]") as HTMLElement;

beforeEach(() => {
  downloads.length = 0;
});

describe("转写模型", () => {
  it("每个模型是卡片里的一行:引擎族和大小是名字旁的小字,不是描边的大写小标", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR(SenseVoice)" },
      { ...base, id: "whisperx", engine: "whisperx", label: "WhisperX" },
    ]);
    const row = await rowOf("FunASR(SenseVoice)");
    expect(row.parentElement?.className).toBe(ADMIN_CARD);
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("rounded-lg");
    const meta = row.querySelector("[data-admin-row-meta]")!;
    expect(meta).toHaveTextContent("funasr · 973 MB");
    expect(meta).not.toHaveClass("uppercase");
    expect(within(row).getByText("中文识别")).toHaveAttribute("data-admin-row-description");
    // 两行是同一张卡片里的兄弟 —— 分隔线由卡片画。
    expect((await rowOf("WhisperX")).parentElement).toBe(row.parentElement);
  });

  it("点下载只下这一个", async () => {
    const user = userEvent.setup();
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR" }]);
    await user.click(within(await rowOf("FunASR")).getByRole("button", { name: /asrModelDownload/ }));
    await waitFor(() => expect(downloads).toEqual(["funasr"]));
  });

  it("装好且跑得起来:右边是已安装,没有按钮", async () => {
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_ready: true }]);
    const row = await rowOf("FunASR");
    const state = within(row).getByText("asrModelInstalled").closest("[data-admin-row-state]");
    expect(state).toHaveAttribute("data-tone", "success");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("运行环境还没测完时说「正在检查」,不下结论也不摆按钮", async () => {
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed", runtime_checked: false }]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("runtimeChecking")).toHaveAttribute("data-admin-row-note");
    expect(within(row).queryByRole("button")).toBeNull();
    expect(row).not.toHaveTextContent("asrModelInstalled");
  });

  it("权重在盘上但跑不起来:说原因,按钮是装运行环境", async () => {
    renderSection([{ ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "installed" }]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("asrModelNoRuntime")).toHaveAttribute("data-tone", "destructive");
    expect(within(row).getByRole("button", { name: /asrModelInstallRuntime/ })).toBeInTheDocument();
  });

  it("有分母时进度条横贯整行,右边报百分比", async () => {
    renderSection([
      {
        ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "downloading",
        downloaded_bytes: 486_500_000, total_bytes: 973_000_000, speed_bps: 2_000_000,
      },
    ]);
    const row = await rowOf("FunASR");
    const footer = row.querySelector("[data-admin-row-footer]")!;
    expect(within(footer as HTMLElement).getByRole("progressbar")).toBeInTheDocument();
    expect(footer).toHaveTextContent("/");
    expect(row.querySelector("[data-admin-row-state]")).toHaveTextContent("50%");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("没有分母(装运行环境)时不画进度条、不报 0%,在说明下面说正在做什么", async () => {
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "downloading", message: "正在安装 torch" },
    ]);
    const row = await rowOf("FunASR");
    expect(row.querySelector("[data-admin-row-footer]")).toBeNull();
    expect(within(row).getByText("正在安装 torch").closest("[data-admin-row-note]")).not.toBeNull();
    expect(row.querySelector("[data-admin-row-state]")).not.toHaveTextContent("%");
  });

  it("失败原因原样显示,按钮变成重试", async () => {
    const user = userEvent.setup();
    renderSection([
      { ...base, id: "funasr", engine: "funasr", label: "FunASR", status: "failed", message: "连不上 ModelScope" },
    ]);
    const row = await rowOf("FunASR");
    expect(within(row).getByText("连不上 ModelScope").closest("[data-admin-row-note]")).toHaveAttribute(
      "data-tone",
      "destructive",
    );
    await user.click(within(row).getByRole("button", { name: /asrModelRetry/ }));
    await waitFor(() => expect(downloads).toEqual(["funasr"]));
  });
});
