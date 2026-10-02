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

//: 一段 AI 生成(数字人)的片段 + 一段自己拍的。
const WITH_AI = {
  ai_asset_ids: ["talking"],
  tracks: [{ id: "V1", kind: "video", clips: [{ id: "c1", asset_id: "talking" }, { id: "c2", asset_id: "shot" }] }],
};

function mount(extra: Record<string, unknown> = WITH_AI) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ExportControl sequence={{ id: "seq-1", width: 1920, height: 1080, fps: 30, ...extra } as never} />
    </QueryClientProvider>,
  );
}

it("时间线上没有 AI 生成的片段:不摆「AI 生成」标识开关", async () => {
  const user = userEvent.setup();
  mount({ ai_asset_ids: [], tracks: [{ id: "V1", kind: "video", clips: [{ id: "c2", asset_id: "shot" }] }] });
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(screen.queryByRole("checkbox", { name: /exportAiLabel/ })).toBeNull();
});

it("有 AI 生成的片段:开关出现,并说清有几段", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(document.querySelector("[data-export-ai-label]")?.textContent).toContain("exportAiLabelFound");
});

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

it("响度标准化默认关;打开后导出带上 loudness_normalize: true,下一次还记得", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  const toggle = screen.getByRole("checkbox", { name: /exportLoudnorm/ });
  expect(toggle).not.toBeChecked();

  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "exportStart" }));
  expect(exportSequence).toHaveBeenCalledWith("seq-1", expect.objectContaining({ loudness_normalize: true }));

  await user.click(await screen.findByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("checkbox", { name: /exportLoudnorm/ })).toBeChecked();
});
