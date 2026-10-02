/** @vitest-environment jsdom */
/**
 * 剪辑页里的取色器:拖动只预览,松手才提交一次。
 *
 * 浏览器在取色器里拖动时连发原生 `input` 事件,选定(关掉取色器)时发一次 `change`。此前每个
 * `input` 都直接写进片段 / 序列 —— 拖一下几十条请求、几十步撤销。这里按浏览器的事件顺序发:
 * 若干次 input,最后一次 change。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { ClipAppearancePanel } from "@/features/editor/ClipAppearancePanel";
import { ColorSwatchInput } from "@/features/editor/ColorSwatchInput";
import { Inspector } from "@/features/editor/Inspector";
import { SubtitlePanel } from "@/features/editor/SubtitlePanel";

/** 取色器里拖过几个颜色,最后在 last 上松手。 */
function dragColor(input: HTMLElement, path: string[]) {
  for (const value of path) fireEvent.input(input, { target: { value } });
  fireEvent.change(input);
}

describe("ColorSwatchInput", () => {
  it("拖动中只预览,change 时提交一次;随后的失焦不再提交", () => {
    const onCommit = vi.fn();
    const onPreview = vi.fn();
    render(<ColorSwatchInput aria-label="c" value="#000000" onCommit={onCommit} onPreview={onPreview} />);
    const input = screen.getByLabelText("c");
    dragColor(input, ["#110000", "#220000", "#330000"]);
    expect(onPreview).toHaveBeenCalledTimes(3);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("#330000");
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("没收到 change 的平台,失焦时兜底提交", () => {
    const onCommit = vi.fn();
    render(<ColorSwatchInput aria-label="c" value="#000000" onCommit={onCommit} />);
    const input = screen.getByLabelText("c");
    fireEvent.input(input, { target: { value: "#00ff00" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith("#00ff00");
  });
});

describe("各处的取色器", () => {
  it("花字颜色:拖动不写片段,松手写一次", () => {
    const onSetEffects = vi.fn();
    const clip = {
      id: "t1", asset_id: null, asset_kind: "", timeline_start: 0, src_in: 0, src_out: 3, speed: 1,
      gain: 1, muted: false, text_override: "Hi", effects: {}, transform: {},
    } as never;
    render(<Inspector workspaceId="w1" selectedClip={clip} assets={[]} isTitleText onDeleteClip={vi.fn()} onSetEffects={onSetEffects} />);
    dragColor(screen.getByLabelText("textColor"), ["#100000", "#200000", "#300000"]);
    expect(onSetEffects).toHaveBeenCalledTimes(1);
    expect(onSetEffects).toHaveBeenCalledWith("t1", { text_style: expect.objectContaining({ color: "#300000" }) });
  });

  it("片段阴影颜色:拖动不写片段,松手写一次", () => {
    const onSetEffects = vi.fn();
    const clip = {
      id: "v1", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 3, speed: 1,
      gain: 1, muted: false, text_override: null, transform: {},
      effects: { appearance: { shadow: { enabled: true, color: "#000000" } } },
    } as never;
    render(<ClipAppearancePanel clip={clip} onSetEffects={onSetEffects} />);
    dragColor(screen.getByLabelText("shadowColor"), ["#000011", "#000022"]);
    expect(onSetEffects).toHaveBeenCalledTimes(1);
  });

  it("字幕颜色:拖动时监视器实时预览,松手才写序列", async () => {
    const onSetStyle = vi.fn();
    const onPreviewStyle = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SubtitlePanel
          sequence={{ id: "s1", workspace_id: "w1", revision: 1, tracks: [] } as never}
          onSetText={vi.fn()}
          onAddSubtitle={vi.fn()}
          onDeleteClip={vi.fn()}
          style={{}}
          onSetStyle={onSetStyle}
          onPreviewStyle={onPreviewStyle}
        />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    dragColor(screen.getByLabelText("subColor"), ["#ff0000", "#ee0000"]);
    expect(onPreviewStyle).toHaveBeenCalledWith(expect.objectContaining({ color: "#ff0000" }));
    expect(onSetStyle).toHaveBeenCalledTimes(1);
    expect(onSetStyle).toHaveBeenCalledWith(expect.objectContaining({ color: "#ee0000" }));
  });
});
