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

import { FrameSlotField, KeyframePairField } from "@/features/ai-studio/FrameSlotField";
import { EMPTY_SLOT } from "@/features/ai-studio/sourceFrames";

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("参考图槽位", () => {
  it("计数说的是**真的挂了几张**,空槽不算", () => {
    const { container } = mount(
      <FrameSlotField
        role="reference_image"
        slots={[{ url: "", assetId: "a", assetName: "a.png" }, { ...EMPTY_SLOT }]}
        limit={9}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.getByText("1/9")).toBeTruthy();
    // 一格缩略图 + 一个加号格
    expect(container.querySelectorAll("img").length).toBe(1);
    expect(container.querySelectorAll("input[type=file]").length).toBe(1);
  });

  it("加到上限就不再给加号 —— 上限是接口的硬约束,不是建议", () => {
    const { container } = mount(
      <FrameSlotField
        role="reference_video"
        slots={[{ url: "", assetId: "a", assetName: "a.mp4" }]}
        limit={1}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(container.querySelector("input[type=file]")).toBeNull();
  });

  it("参考图能一次选多个 —— 挂九张让人点九次是没道理的", () => {
    const { container } = mount(
      <FrameSlotField role="reference_image" slots={[{ ...EMPTY_SLOT }]} limit={9} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.hasAttribute("multiple")).toBe(true);
  });

  it("只收一份的角色不给多选", () => {
    const { container } = mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=file]")?.hasAttribute("multiple")).toBe(false);
  });

  it("面板里不再有 URL 输入框", () => {
    // 那一栏几乎没人用(素材本来就在素材库里),却让每个角色多占两行。外链这条路本身留着,
    // 智能体和工作流照样能发 <role>_url,只是不再占据面板。
    const { container } = mount(
      <FrameSlotField role="reference_image" slots={[{ ...EMPTY_SLOT }]} limit={9} onChange={vi.fn()} workspaceId="w" />,
    );
    expect(container.querySelector("input[type=text]")).toBeNull();
  });

  it("上限为 1 时不显示计数 —— 1/1 是句废话", () => {
    mount(
      <FrameSlotField role="source_video" slots={[{ ...EMPTY_SLOT }]} limit={1} onChange={vi.fn()} workspaceId="w" />,
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
    // 锁住时连加号格都不画 —— 留一个点不动的按钮,用户点了没反应,那比直接没有更费解。
    const { container } = mount(
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
    expect(container.querySelector("input[type=file]")).toBeNull();
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


describe("首尾帧是一对", () => {
  const filled = (id: string) => [{ url: "", assetId: id, assetName: id }];

  it("并排两格,中间一个交换按钮", () => {
    mount(
      <KeyframePairField
        first={filled("a")}
        last={filled("b")}
        showLast
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.getByRole("button", { name: "genSwapKeyframes" })).toBeTruthy();
  });

  it("交换就是把两边对调,不用删掉重传", () => {
    // 「拍反了」是最常见的手误,删两张重传是最笨的补救。
    const onChange = vi.fn();
    mount(
      <KeyframePairField first={filled("a")} last={filled("b")} showLast onChange={onChange} workspaceId="w" />,
    );
    screen.getByRole("button", { name: "genSwapKeyframes" }).click();
    expect(onChange).toHaveBeenCalledWith({ first: filled("b"), last: filled("a") });
  });

  it("只挂了一边时换不动 —— 那不是对调,是搬家", () => {
    mount(
      <KeyframePairField first={filled("a")} last={[{ ...EMPTY_SLOT }]} showLast onChange={vi.fn()} workspaceId="w" />,
    );
    expect(screen.getByRole("button", { name: "genSwapKeyframes" }).hasAttribute("disabled")).toBe(true);
  });

  it("模型不认尾帧时不画箭头,也不画第二格", () => {
    mount(
      <KeyframePairField
        first={[{ ...EMPTY_SLOT }]}
        last={[{ ...EMPTY_SLOT }]}
        showLast={false}
        onChange={vi.fn()}
        workspaceId="w"
      />,
    );
    expect(screen.queryByRole("button", { name: "genSwapKeyframes" })).toBeNull();
  });
});
