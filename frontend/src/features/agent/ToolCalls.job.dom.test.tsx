/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getJob: vi.fn(), getAsset: vi.fn() }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("@/api/client", () => ({
  getJob: mocks.getJob,
  getAsset: mocks.getAsset,
  assetFileUrl: (id: string) => `/api/assets/${id}/file`,
  assetPreviewUrl: (id: string) => `/api/assets/${id}/preview`,
}));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { ToolCalls } from "@/features/agent/ToolCalls";

describe("异步工具的任务状态", () => {
  it("折叠行不把 job id 当成摘要", () => {
    mocks.getJob.mockResolvedValue({ id: "j3", status: "running", message: "", error: null, error_summary: null, error_detail: null, error_hint: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <ToolCalls tools={[{ id: "t3", name: "get_job", status: "running", args: { job_id: "108d32cf3bd542469f90134f80dd3c27" } }]} />
      </QueryClientProvider>,
    );
    expect(container.querySelector("[data-tool-call] button")?.textContent).not.toContain("108d32cf");
  });

  it("任务失败时不把工具调用画成成功", async () => {
    mocks.getJob.mockResolvedValue({
      id: "j1",
      status: "failed",
      message: "",
      error: "上游拒绝了这次运行",
      error_summary: "任务失败:上游拒绝",
      error_detail: null,
      error_hint: null,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <ToolCalls tools={[{ id: "t1", name: "run_workflow", status: "done", result: { job_id: "j1" } }]} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(container.querySelector("[data-tool-call]")?.getAttribute("data-tool-status")).toBe("error"));
    expect(container.textContent).toContain("任务失败:上游拒绝");
  });

  it("任务完成后把产物接进媒体预览", async () => {
    mocks.getJob.mockResolvedValue({
      id: "j2",
      status: "succeeded",
      message: "",
      error: null,
      error_summary: null,
      error_detail: null,
      error_hint: null,
      result: { asset_ids: ["a1"] },
    });
    mocks.getAsset.mockResolvedValue({ id: "a1", kind: "audio", name: "片头音乐.mp3" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <ImagePreviewProvider>
          <ToolCalls
            tools={[{
              id: "t2",
              name: "generate_sound",
              status: "done",
              args: { prompt: "片头音乐", parameters: { caption: "一段明亮的电子流行乐", lyrics: "[Instrumental]" } },
              result: { job_id: "j2" },
            }]}
          />
        </ImagePreviewProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(container.querySelector('[data-media-preview="a1"]')).not.toBeNull());
    expect(container.textContent).toContain("片头音乐.mp3");
    expect(container.querySelector('[data-tool-section="input"]')).not.toBeNull();
    expect(container.querySelector('[data-tool-section="output"] [data-media-preview="a1"]')).not.toBeNull();
    //: 输入是给人读的字段,原始 JSON 只折在 details 里,不再默认铺满。
    expect(container.querySelector('[data-tool-section="input"]')?.textContent).toContain("一段明亮的电子流行乐");
    expect(container.querySelector('[data-tool-section-heading="input"]')).not.toBeNull();
    expect(container.querySelector('[data-tool-section-heading="output"]')).not.toBeNull();
    expect(container.querySelector('[data-tool-section="output"] details')?.textContent).toContain("原始输出");
    expect(container.querySelector('[data-tool-section="input"] details[open]')).toBeNull();
  });
});
