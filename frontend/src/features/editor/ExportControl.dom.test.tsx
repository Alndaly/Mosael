/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 导出时的「AI 生成」显式标识(ADR 0028 §5):**默认开、允许关**;关的时候当场写明后果;**不记住关** ——
 * 下一次打开导出框又是开着的(关过一次之后每一片都悄悄不带标识,发布的人未必记得)。
 */

const exportSequence = vi.fn(async () => ({ id: "job-1", status: "queued" }));
vi.mock("@/api/domains/editor", () => ({ exportSequence: (...args: unknown[]) => exportSequence(...(args as [])) }));
//: 任务一查就是做完了 —— 好让按钮回到「导出」,再打开一次看开关是不是回到了开着。
vi.mock("@/api/transport", () => ({ api: vi.fn(async () => ({ id: "job-1", status: "succeeded" })) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ExportControl } from "./ExportControl";

beforeEach(() => {
  exportSequence.mockClear();
  localStorage.clear();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ExportControl sequence={{ id: "seq-1", width: 1920, height: 1080, fps: 30 } as never} />
    </QueryClientProvider>,
  );
}

it("默认开着;关掉当场写明后果,导出时带上 ai_label: false;下一次打开又是开着的", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  const toggle = screen.getByRole("checkbox", { name: /exportAiLabel/ });
  expect(toggle).toBeChecked();
  expect(document.querySelector("[data-export-ai-label-off]")).toBeNull();

  await user.click(toggle);
  expect(screen.getByRole("alert").textContent).toBe("exportAiLabelOffWarning");
  await user.click(screen.getByRole("button", { name: "exportStart" }));
  expect(exportSequence).toHaveBeenCalledWith("seq-1", expect.objectContaining({ ai_label: false }));
  expect(localStorage.getItem("mosael.export.params") ?? "").not.toContain("ai_label");

  await user.click(await screen.findByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("checkbox", { name: /exportAiLabel/ })).toBeChecked();
});
