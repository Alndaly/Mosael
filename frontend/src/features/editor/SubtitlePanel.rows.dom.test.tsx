/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 字幕列表的每一行:改起止时间、清空文字 = 删掉这条、播放时跟着当前字幕滚动。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { useEditorStore } from "@/features/editor/editorStore";

const sequence = {
  id: "s1", workspace_id: "w1", revision: 1,
  tracks: [{
    id: "t1", kind: "subtitle",
    clips: ["第一条", "第二条", "第三条"].map((text, index) => ({
      id: `c${index}`, asset_id: null, asset_kind: "", timeline_start: index * 5, src_in: 0, src_out: 3, speed: 1, text_override: text,
    })),
  }],
} as never;

function renderPanel() {
  const handlers = { onSetText: vi.fn(), onDeleteClip: vi.fn(), onSetTiming: vi.fn() };
  return { ...handlers, ...render(
    <QueryClientProvider client={new QueryClient()}>
      <SubtitlePanel sequence={sequence} onAddSubtitle={vi.fn()} {...handlers} />
    </QueryClientProvider>,
  ) };
}

afterEach(() => {
  act(() => {
    useEditorStore.getState().setPlaying(false);
    useEditorStore.getState().setPlayhead(0);
  });
});

describe("字幕列表的每一行", () => {
  it("改起止时间:一次 trim(起点、源时长),回车提交", async () => {
    const user = userEvent.setup();
    const { onSetTiming } = renderPanel();
    await user.click(screen.getAllByRole("button", { name: "subtitleEditTiming" })[1]);
    const start = screen.getByRole("textbox", { name: "subtitleStart" });
    const end = screen.getByRole("textbox", { name: "subtitleEnd" });
    await user.clear(start);
    await user.type(start, "5.5");
    await user.clear(end);
    await user.type(end, "00:09{Enter}");
    expect(onSetTiming).toHaveBeenCalledOnce();
    expect(onSetTiming).toHaveBeenCalledWith("c1", { timeline_start: 5.5, src_in: 0, src_out: 3.5 });
  });

  it("清空文字 = 删掉这条字幕(此前清空之后失焦,文字原样回来)", async () => {
    const user = userEvent.setup();
    const { onDeleteClip, onSetText } = renderPanel();
    const box = screen.getByDisplayValue("第二条");
    await user.clear(box);
    await user.tab();
    expect(onDeleteClip).toHaveBeenCalledWith("c1");
    expect(onSetText).not.toHaveBeenCalled();
  });

  it("播放时当前字幕滚进视野;停着的时候不拽", () => {
    const { container } = renderPanel();
    // 列表是窗口化的(T7):没渲染的行没有 DOM,按算出来的偏移滚动容器,而不是 scrollIntoView。
    const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
    act(() => useEditorStore.getState().setPlayhead(11));
    expect(scroller.scrollTop).toBe(0);
    act(() => useEditorStore.getState().setPlaying(true));
    expect(scroller.scrollTop).toBeGreaterThan(0);
  });
});
