/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 一个槽位控件要把三件事表现出来:**能挂几份**、**现在挂了几份**、**为什么现在不能挂**。
 *
 * 三件事都只在界面上,后端拦得住但那已经太晚了 —— 用户挂满九张、点了生成、等了几秒,
 * 才被告知这一组根本不能和首帧一起用。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/f/${id}`,
  assetThumbnailUrl: (id: string) => `/t/${id}`,
  importAsset: vi.fn(),
}));

import { FrameSlotField } from "@/features/ai-studio/FrameSlotField";
import { EMPTY_SLOT } from "@/features/ai-studio/sourceFrames";

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("参考图槽位", () => {
  it("上限大于 1 时显示计数和「再加一份」", () => {
    mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ url: "", assetId: "a", assetName: "a.png" }, { ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.getByText("1/9")).toBeTruthy();
    expect(screen.getByText("genReferenceAdd")).toBeTruthy();
  });

  it("加到上限就不再给加号 —— 上限是接口的硬约束,不是建议", () => {
    mount(
      <FrameSlotField
        role="reference_video"
        slots={[{ url: "", assetId: "a", assetName: "a.mp4" }]}
        limit={1}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.queryByText("genReferenceAdd")).toBeNull();
  });

  it("上限为 1 时不显示计数 —— 首尾帧长得和以前一模一样", () => {
    mount(
      <FrameSlotField role="first_frame" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(screen.queryByText("0/1")).toBeNull();
  });

  it("被另一组锁住时说清楚为什么,而不是只灰掉", () => {
    // 只灰不说的话,用户看到的是一个"坏了"的控件,而不是"这条路我已经选了另一条"。
    mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
        disabled
        disabledReason="不能一起用"
      />,
    );
    expect(screen.getByText("不能一起用")).toBeTruthy();
    expect(screen.getByRole("button", { name: /genReferenceImageUpload/ }).hasAttribute("disabled")).toBe(true);
  });
});

describe("视频输入槽位", () => {
  it("待编辑的视频收 video/*,不是 image/*", () => {
    // 收 image/* 的话,用户在系统文件面板里一个视频都点不亮。
    const { container } = mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.getAttribute("accept")).toBe("video/*");
  });

  it("参考音频收 audio/*", () => {
    const { container } = mount(
      <FrameSlotField role="reference_audio" slots={[{ ...EMPTY_SLOT }]} limit={3} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.getAttribute("accept")).toBe("audio/*");
  });
});
