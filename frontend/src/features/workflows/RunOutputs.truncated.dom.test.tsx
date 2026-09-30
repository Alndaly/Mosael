/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 长文字在运行事件里只留了开头(后端 run_outputs)。此前界面上看不出它被截过,「复制」拿到的也是
 * 截断版 —— 一段三千字的模型回复,用户以为自己拿到了全部。
 */

const transport = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/api/transport", async (original) => ({ ...(await original<typeof import("@/api/transport")>()), ...transport }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import type { RegistryLike } from "@/features/workflows/analyze";
import { RunOutputs } from "@/features/workflows/RunOutputs";
import type { Step } from "@/features/workflows/runSteps";

const registry: RegistryLike = { get: () => ({ output_types: { text: "text" } }) };
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
