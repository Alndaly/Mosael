/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 长文字在运行事件里只留了开头(后端 run_outputs)。此前界面上看不出它被截过,「复制」拿到的也是
 * 截断版 —— 一段三千字的模型回复,用户以为自己拿到了全部。
 */

const transport = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/api/transport", async (original) => ({ ...(await original<typeof import("@/api/transport")>()), ...transport }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
const download = vi.hoisted(() => ({ saveBlobToDisk: vi.fn() }));
vi.mock("@/lib/download", () => download);

import type { RegistryLike } from "@/features/workflows/analyze";
import { RunOutputs } from "@/features/workflows/RunOutputs";
import type { Step } from "@/features/workflows/runSteps";

const registry: RegistryLike = { get: () => ({ output_types: { text: "text", results: "list" } }) };
const FULL = "长".repeat(2600);
const writeText = vi.fn(async () => undefined);

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  transport.api.mockResolvedValue({ value: FULL });
});

function mount(step: Step) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RunOutputs registry={registry} nodeType="llm" step={step} />
    </QueryClientProvider>,
  );
}

it("截断了的输出:标明全文多长;复制拿到的是按这次运行取回来的全文", async () => {
  mount({
    nid: "llm-1",
    name: "LLM",
    status: "done",
    jobId: "job-9",
    outputs: { text: `${FULL.slice(0, 2000)}…` },
    truncated: { text: FULL.length },
  });
  expect(screen.getByText("wfOutputTruncated").textContent).toBe("wfOutputTruncated");
  fireEvent.click(screen.getByTitle("copy"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(FULL));
  expect(transport.api).toHaveBeenCalledWith("/api/workflows/runs/job-9/outputs/llm-1/text");
});

it("没截断的输出:不说截断,复制直接给值,不去取", async () => {
  mount({ nid: "llm-1", name: "LLM", status: "done", jobId: "job-9", outputs: { text: "短的" } });
  expect(document.querySelector("[data-output-truncated]")).toBeNull();
  expect(screen.queryByLabelText("wfOutputDownload")).toBeNull();
  fireEvent.click(screen.getByTitle("copy"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("短的"));
  expect(transport.api).not.toHaveBeenCalled();
});

it("嵌套里的长文字被截了(循环 results、子图 output 里的):标明是哪几处,每一处复制 / 下载都按路径取全文", async () => {
  //: 此前只认顶层那一层的截断:循环每一项里的长文案在快照里只剩开头,界面上看不出来,复制到的也是开头。
  //: 后端事件的 truncated 是 {从输出名开始的点号路径: 全文字数},取全文的接口 key 就是这条路径。
  const head = `${FULL.slice(0, 500)}…`;
  mount({
    nid: "loop-1",
    name: "逐镜",
    status: "done",
    jobId: "job-9",
    outputs: { results: [{ text: "短的" }, { text: head }] },
    truncated: { "results.1.text": FULL.length },
  });
  const notes = [...document.querySelectorAll<HTMLElement>("[data-output-truncated]")];
  expect(notes).toHaveLength(1);
  expect(notes[0].textContent).toContain("wfOutputNestedTruncated");
  const item = notes[0].querySelector<HTMLElement>('[data-truncated-path="results.1.text"]')!;
  expect(item.textContent).toContain("results.1.text");

  fireEvent.click(within(item).getByTitle("copy"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(FULL));
  expect(transport.api).toHaveBeenCalledWith("/api/workflows/runs/job-9/outputs/loop-1/results.1.text");

  fireEvent.click(within(item).getByLabelText("wfOutputDownload"));
  await waitFor(() => expect(download.saveBlobToDisk).toHaveBeenCalled());
  const [blob, name] = download.saveBlobToDisk.mock.calls[0] as [Blob, string];
  expect(name).toBe("results.1.text.txt");
  expect(await blob.text()).toBe(FULL);
});

it("不是从这个输出名开始的点号路径不算它的:方括号写法、别的输出", () => {
  mount({
    nid: "loop-1",
    name: "逐镜",
    status: "done",
    jobId: "job-9",
    outputs: { results: [{ text: "开头…" }] },
    truncated: { "results[0].text": 9000, "resultsX.0": 9000 },
  });
  expect(document.querySelector("[data-output-truncated]")).toBeNull();
});
