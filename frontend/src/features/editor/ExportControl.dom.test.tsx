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
  tracks: [{
    id: "V1", kind: "video",
    clips: [{ id: "c1", asset_id: "talking", asset_kind: "video" }, { id: "c2", asset_id: "shot", asset_kind: "video" }],
  }],
};
//: 视频轨空着,只有音频轨上一段声音(用户:「视频轨为空时导出报错」)。
const AUDIO_ONLY = {
  ai_asset_ids: [],
  tracks: [
    { id: "V1", kind: "video", clips: [] },
    { id: "A1", kind: "audio", clips: [{ id: "a1", asset_id: "voice", asset_kind: "audio" }] },
  ],
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
  mount({ ai_asset_ids: [], tracks: [{ id: "V1", kind: "video", clips: [{ id: "c2", asset_id: "shot", asset_kind: "video" }] }] });
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(screen.queryByRole("checkbox", { name: /exportAiLabel/ })).toBeNull();
});

it("有 AI 生成的片段:开关出现,并说清有几段", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(document.querySelector("[data-export-ai-label]")?.textContent).toContain("exportAiLabelFound");
});

it("默认关着(画面上不加「AI 生成」);打开才带上 ai_label: true;不记住,下一次打开又是关着的", async () => {
  // 维护者 2026-10-06:「生成的视频不要有『AI 生成』这种额外字幕」(ADR 0028 后续修正)。
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  const toggle = screen.getByRole("checkbox", { name: /exportAiLabel/ });
  expect(toggle).not.toBeChecked();
  await user.click(screen.getByRole("button", { name: "exportStart" }));
  expect(exportSequence).toHaveBeenLastCalledWith("seq-1", expect.objectContaining({ ai_label: false }));

  await user.click(await screen.findByRole("button", { name: "exportVideo" }));
  await user.click(screen.getByRole("checkbox", { name: /exportAiLabel/ }));
  expect(screen.queryByRole("alert"), "开着关着都不再弹警告").toBeNull();
  await user.click(screen.getByRole("button", { name: "exportStart" }));
  expect(exportSequence).toHaveBeenLastCalledWith("seq-1", expect.objectContaining({ ai_label: true }));
  expect(localStorage.getItem("mosael.export.params") ?? "").not.toContain("ai_label");

  await user.click(await screen.findByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("checkbox", { name: /exportAiLabel/ })).not.toBeChecked();
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

it("默认导出 MP4 视频;换成音频就只剩格式和响度两项,导出带上选的格式,下一次还记得", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("radio", { name: "exportKindVideo" })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("combobox", { name: "exportFormat" })).toHaveTextContent("exportFormat_mp4");

  await user.click(screen.getByRole("radio", { name: "exportKindAudio" }));
  expect(screen.getByRole("combobox", { name: "exportFormat" })).toHaveTextContent("exportFormat_mp3");
  expect(screen.queryByText("exportResolution"), "声音没有分辨率").toBeNull();
  expect(screen.queryByRole("checkbox", { name: /exportAiLabel/ }), "画面上的标识无处可加").toBeNull();
  expect(screen.getByRole("checkbox", { name: /exportLoudnorm/ })).toBeInTheDocument();

  await user.click(screen.getByRole("combobox", { name: "exportFormat" }));
  await user.click(await screen.findByRole("option", { name: "exportFormat_wav" }));
  await user.click(screen.getByRole("button", { name: "exportStart" }));
  expect(exportSequence).toHaveBeenLastCalledWith("seq-1", expect.objectContaining({ format: "wav", ai_label: false }));

  await user.click(await screen.findByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("radio", { name: "exportKindAudio" })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("combobox", { name: "exportFormat" })).toHaveTextContent("exportFormat_wav");
});

it("时间线上没有画面:导出视频前说清会是黑场,一下就能换成导出音频", async () => {
  const user = userEvent.setup();
  mount(AUDIO_ONLY);
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(screen.getByRole("status")).toHaveTextContent("exportNoPicture");

  await user.click(screen.getByRole("button", { name: "exportSwitchToAudio" }));
  expect(screen.getByRole("radio", { name: "exportKindAudio" })).toHaveAttribute("aria-checked", "true");
  expect(screen.queryByRole("status"), "换成音频后提示收起").toBeNull();
});

it("有画面的时间线不摆黑场提示", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("button", { name: "exportVideo" }));
  expect(document.querySelector("[data-export-no-picture]")).toBeNull();
});
